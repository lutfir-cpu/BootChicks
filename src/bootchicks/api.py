"""Thin local HTTP surface with one explicit queue worker and idempotent triggers."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.staticfiles import StaticFiles

from .negotiation import execute
from .providers import DEFAULT_PROMPTS, PROMPT_VERSION
from .scenario import DATA_DIR, SCENARIOS, load_snapshot, request_snapshot
from .schemas import RunRequest, WorkflowInput
from .store import IdempotencyConflict, Store

SAMPLE_TRIGGER = DATA_DIR / "fixtures/real_trigger.json"


def scenario_options():
    """Describe each scenario's airports and gates so clients can offer valid busy periods."""
    options = []
    for scenario_id, text in SCENARIOS.items():
        snapshot = load_snapshot(scenario_id)
        options.append(
            {
                "id": scenario_id,
                **text,
                "preferred_gate": snapshot.preferred_gate,
                "airports": [
                    {
                        "iata_code": airport.iata_code,
                        "kind": kind,
                        "gates": [gate.id for gate in airport.gates],
                    }
                    for kind, airport in [
                        ("destination", snapshot.destination),
                        *(("alternate", a) for a in snapshot.alternates),
                    ]
                ],
            }
        )
    return options


def create_app(database=None, provider_factory=None, frontend_dir=None):
    database = database or os.getenv(
        "BOOTCHICKS_DATABASE", "data/runs/bootchicks.sqlite"
    )
    frontend_dir = frontend_dir or os.getenv("BOOTCHICKS_FRONTEND_DIR")

    @asynccontextmanager
    async def lifespan(app):
        store = Store(database)
        with store.process_lock():
            store.recover_interrupted()
            queue = asyncio.Queue()
            app.state.store, app.state.queue = store, queue

            async def worker():
                while True:
                    run_id, request = await queue.get()
                    try:
                        provider = (
                            provider_factory(request) if provider_factory else None
                        )
                        await execute(store, run_id, request, provider)
                    except asyncio.CancelledError:
                        store.fail(run_id, "WORKER_STOPPED")
                        raise
                    except Exception as exc:  # noqa: BLE001 - durable job boundary; never expose raw provider errors.
                        store.fail(run_id, type(exc).__name__)
                    finally:
                        queue.task_done()

            task = asyncio.create_task(worker())
            try:
                yield
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                store.recover_interrupted()

    app = FastAPI(
        title="BootChicks simulation backend", version="0.2.0", lifespan=lifespan
    )

    @app.post("/runs", status_code=202)
    async def start_run(
        payload: RunRequest | WorkflowInput,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
        ],
    ):
        request = (
            RunRequest(trigger=payload, mode=payload.mode)
            if isinstance(payload, WorkflowInput)
            else payload
        )
        try:
            request_snapshot(
                request, app.state.store.airport_capacities(request.capacity_version)
            )
            run_id, created = app.state.store.open_run(idempotency_key, request)
        except IdempotencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc).splitlines()[0][:200]) from exc
        if created:
            app.state.queue.put_nowait((run_id, request))
        return {
            "run_id": run_id,
            "created": created,
            "status": app.state.store.run(run_id)["status"],
            "result_url": f"/runs/{run_id}",
        }

    @app.get("/runs/{run_id}")
    async def read_run(run_id: str):
        try:
            return app.state.store.run(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Run not found") from exc

    @app.get("/options")
    async def read_options():
        return {
            "scenarios": scenario_options(),
            "live_available": bool(os.getenv("ANTHROPIC_API_KEY")),
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            "default_prompts": DEFAULT_PROMPTS,
            "prompt_version": PROMPT_VERSION,
            "sample_trigger": WorkflowInput.model_validate_json(
                SAMPLE_TRIGGER.read_bytes()
            ),
        }

    @app.get("/airport-capacities")
    async def read_capacities():
        return list(app.state.store.airport_capacities().values())

    @app.get("/airport-capacities/{iata_code}")
    async def read_capacity(iata_code: str):
        capacity = app.state.store.airport_capacities().get(iata_code.upper())
        if capacity is None:
            raise HTTPException(404, "Airport capacity not found")
        return capacity

    @app.get("/runs/{run_id}/events")
    async def read_events(run_id: str, format: Literal["json", "jsonl"] = "json"):
        try:
            events = app.state.store.events(run_id)
        except KeyError as exc:
            raise HTTPException(404, "Run not found") from exc
        if format == "jsonl":
            return Response(
                "".join(e.model_dump_json() + "\n" for e in events),
                media_type="application/x-ndjson",
            )
        return events

    if frontend_dir and Path(frontend_dir, "index.html").is_file():
        # Mounted last so API routes keep priority over the built single-page app.
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
