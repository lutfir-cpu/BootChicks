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
}


def without_reservations(evaluation):
    if evaluation is None:
        return None
    return {k: v for k, v in evaluation.items() if k != "reservations"}


def trim(event):
    payload = event["payload"]
    if event["kind"] == "PREPARED":
        snapshot = payload["snapshot"]
        airports = [snapshot["destination"], *snapshot["alternates"]]
        payload = {
            "snapshot": {
                "clock": snapshot["clock"],
                "preferred_gate": snapshot["preferred_gate"],
                "destination": {k: airports[0][k] for k in ("iata_code", "paths")},
                "alternates": [
                    {k: a[k] for k in ("iata_code", "paths")} for a in airports[1:]
                ],
            }
        }
    elif event["kind"] == "PROPOSAL_BOARD":
        payload = {
            "evaluations": [
                {
                    **without_reservations(e),
                    # The proposal board only shows which checks pass.
                    "checks": [
                        {k: c[k] for k in ("constraint_id", "domain", "passed")}
                        for c in e["checks"]
                    ],
                }
                for e in payload["evaluations"]
            ]
        }
    elif event["kind"] == "NO_VALIDATED_PLAN":
        payload = {
            "rejections": [
                {
                    "plan_hash": r["plan_hash"],
                    "failed": [
                        {"constraint_id": c["constraint_id"], "domain": c["domain"]}
                        for c in r["failed"]
                    ],
                }
                for r in payload["rejections"]
            ]
        }
    return {**event, "payload": payload}


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
                events = [
                    trim(e)
                    for e in client.get(f"/runs/{run_id}/events").json()
                    if e["kind"] not in ("ROUND_INPUT", "BASELINE")
                ]
                result = {
                    **state["result"],
                    "evaluation": without_reservations(state["result"]["evaluation"]),
                    "baseline": without_reservations(state["result"]["baseline"]),
                }
                fixture = {"result": result, "events": events}
                (OUT / f"{name}.json").write_text(
                    json.dumps(fixture, separators=(",", ":")) + "\n"
                )


if __name__ == "__main__":
    main()
