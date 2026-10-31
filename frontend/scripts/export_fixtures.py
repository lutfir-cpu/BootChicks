"""Regenerate the frontend test fixtures from real stub runs of the backend.

Run from the repository root: python frontend/scripts/export_fixtures.py
Fixtures keep only the fields the UI reads, so they stay small and readable.
"""

import json
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bootchicks.api import create_app

OUT = Path(__file__).resolve().parents[1] / "src/test/fixtures"
RUNS = {
    "consensus": {"scenario_id": "runway_closure_gate_conflict_v1", "mode": "stub"},
    "escalated": {"scenario_id": "insufficient_fuel", "mode": "stub"},
    "fallback": {"scenario_id": "diversion", "mode": "fallback"},
}


def without_reservations(evaluation):
    if evaluation is None:
        return None
    return {k: v for k, v in evaluation.items() if k != "reservations"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory) / "fixtures.sqlite")) as client:
            options = client.get("/options").json()
            (OUT / "options.json").write_text(json.dumps(options, indent=1) + "\n")
            for name, body in RUNS.items():
                run_id = client.post(
                    "/runs",
                    json={**body, "environment": name},
                    headers={"Idempotency-Key": name},
                ).json()["run_id"]
                while (state := client.get(f"/runs/{run_id}").json())["status"] in (
                    "QUEUED",
                    "RUNNING",
                ):
                    time.sleep(0.02)
                decisions = client.get(f"/runs/{run_id}/decisions").json()
                result = {
                    **state["result"],
                    "evaluation": without_reservations(state["result"]["evaluation"]),
                    "baseline": without_reservations(state["result"]["baseline"]),
                }
                fixture = {"result": result, "decisions": decisions}
                (OUT / f"{name}.json").write_text(
                    json.dumps(fixture, separators=(",", ":")) + "\n"
                )


if __name__ == "__main__":
    main()
