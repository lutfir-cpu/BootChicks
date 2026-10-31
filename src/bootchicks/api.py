"""Thin local HTTP surface with one explicit queue worker and idempotent triggers."""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Response

from .negotiation import execute
from .scenario import load_snapshot
from .schemas import RunRequest, WorkflowInput
from .store import IdempotencyConflict, Store


def create_app(database=None, provider_factory=None):
    database = database or os.getenv(
        "BOOTCHICKS_DATABASE", "data/runs/bootchicks.sqlite"
    )

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
            load_snapshot(
                request.trigger.scenario_id if request.trigger else request.scenario_id,
                request.trigger,
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

    return app
