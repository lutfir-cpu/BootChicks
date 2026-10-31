"""Select or import genuine rows, run a simulation, export its evidence or serve the API."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from .catalog import import_flights
from .ingestion import select_row
from .negotiation import execute
from .scenario import request_snapshot
from .schemas import RunRequest, WorkflowInput
from .store import Store


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select-row")
    select.add_argument("--data-dir", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    flights = commands.add_parser(
        "import-flights",
        help="Catalogue every disrupted flight the simulator supports, so the app can pick one",
    )
    flights.add_argument(
        "--data-dir", type=Path, default=Path("data/raw/flight-delays")
    )
    run = commands.add_parser("run")
    run.add_argument("--trigger", type=Path)
    run.add_argument(
        "--scenario",
        choices=[
            "runway_closure_gate_conflict_v1",
            "insufficient_fuel",
            "no_gate",
            "diversion",
        ],
        default="runway_closure_gate_conflict_v1",
    )
    run.add_argument(
        "--mode",
        choices=["stub", "live", "fallback", "recorded_replay"],
        default="stub",
    )
    run.add_argument("--idempotency-key", default=None)
    run.add_argument("--output", type=Path)
    run.add_argument("--round-timeout", type=float, default=12)
    run.add_argument("--total-timeout", type=float, default=30)
    run.add_argument("--capacity-version")
    run.add_argument(
        "--gate-occupancies",
        type=Path,
        help="JSON list of airport, gate_id, start_min and end_min relative to scenario start",
    )
    export = commands.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("--format", choices=["json", "jsonl"], default="json")
    export.add_argument("--output", type=Path)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--frontend-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "frontend/dist",
        help="Built React app to serve at /; skipped when it has not been built",
    )
    for command in (flights, run, export, serve):
        command.add_argument(
            "--database", type=Path, default=Path("data/runs/bootchicks.sqlite")
        )
    args = parser.parse_args()
    try:
        if args.command == "select-row":
            trigger = select_row(args.data_dir)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(trigger.model_dump_json(indent=2) + "\n")
            print(
                f"Selected source CSV line {trigger.provenance.csv_line}: {trigger.flight_row.AIRLINE}-{trigger.flight_row.FLIGHT_NUMBER}; saved {args.output}"
            )
            return
        if args.command == "serve":
            import uvicorn

            os.environ["BOOTCHICKS_DATABASE"] = str(args.database)
            os.environ["BOOTCHICKS_FRONTEND_DIR"] = str(args.frontend_dir)
            uvicorn.run(
                "bootchicks.api:create_app",
                factory=True,
                host="127.0.0.1",
                port=args.port,
                workers=1,
            )
            return
        store = Store(args.database)
        if args.command == "import-flights":
            print(
                f"Scanning {args.data_dir / 'flights.csv'}; this takes a few minutes."
            )
            summary = import_flights(
                store,
                args.data_dir,
                progress=lambda n: print(f"  {n:,} flights found", end="\r"),
            )
            print(
                f"Imported {summary['supported']:,} supported flights out of "
                f"{summary['disrupted']:,} disrupted and {summary['rows']:,} total rows into {args.database}."
            )
            for reason, count in summary["skipped"].items():
                print(f"  skipped {count:,}: {reason}")
            return
        if args.command == "run":
            trigger = (
                WorkflowInput.model_validate_json(args.trigger.read_bytes())
                if args.trigger
                else None
            )
            if trigger:
                trigger = trigger.model_copy(
                    update={"mode": args.mode, "scenario_id": args.scenario}
                )
            request = RunRequest(
                trigger=trigger,
                mode=args.mode,
                scenario_id=args.scenario,
                round_timeout_seconds=args.round_timeout,
                total_timeout_seconds=args.total_timeout,
                capacity_version=args.capacity_version,
                gate_occupancies=json.loads(args.gate_occupancies.read_text())
                if args.gate_occupancies
                else (),
            )
            request_snapshot(
                request, store.airport_capacities(request.capacity_version)
            )
            with store.process_lock():
                store.recover_interrupted()
                run_id, created = store.open_run(
                    args.idempotency_key or str(uuid4()), request
                )
                if created:
                    try:
                        asyncio.run(execute(store, run_id, request))
                    except Exception as exc:  # noqa: BLE001 - record interrupted/invalid jobs without leaking details.
                        store.fail(run_id, type(exc).__name__)
                        raise
                output = json.dumps(store.run(run_id), indent=2, allow_nan=False)
        else:
            output = (
                "".join(e.model_dump_json() + "\n" for e in store.events(args.run_id))
                if args.format == "jsonl"
                else json.dumps(store.run(args.run_id), indent=2, allow_nan=False)
            )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n")
            print(f"Saved {args.output}")
        else:
            print(output)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(
            f"Cannot complete workflow: {str(exc).splitlines()[0][:250]}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
