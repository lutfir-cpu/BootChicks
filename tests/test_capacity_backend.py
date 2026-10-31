from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from bootchicks.api import create_app
from bootchicks.constraints import evaluate
from bootchicks.scenario import actions, candidate, load_snapshot
from bootchicks.schemas import RunRequest
from bootchicks.store import Store


def test_gate_schedule_boundaries_and_environment_identity(tmp_path):
    from bootchicks.schemas import GateOccupancy

    capacities = Store(tmp_path / "runs.sqlite").airport_capacities()
    busy = GateOccupancy(airport="DFW", gate_id="B2", start_min=0, end_min=33)
    snapshot = load_snapshot(
        "runway_closure_gate_conflict_v1",
        capacities=capacities,
        gate_occupancies=(busy,),
    )
    action = next(
        a
        for a in actions(snapshot)
        if a.gate_id == "B2"
        and a.landing_slot == snapshot.clock + timedelta(minutes=25)
        and a.approach_id == "standard"
        and a.taxi_path_id == "Bravo"
        and a.crew_id == "C2"
    )
    assert evaluate(snapshot, candidate(snapshot, action)).feasible
    overlap = busy.model_copy(update={"end_min": 34})
    blocked = load_snapshot(
        "runway_closure_gate_conflict_v1",
        capacities=capacities,
        gate_occupancies=(overlap,),
    )
    report = evaluate(blocked, candidate(blocked, action))
    assert not next(
        c for c in report.checks if c.constraint_id == "GATE_BOOKING"
    ).passed
    assert blocked.environment_id != snapshot.environment_id
    assert (
        load_snapshot(
            "runway_closure_gate_conflict_v1",
            capacities=capacities,
            gate_occupancies=(busy,),
        ).environment_id
        == snapshot.environment_id
    )


def test_challenge_limits_are_authoritative_and_source_bound(tmp_path):
    capacities = Store(tmp_path / "runs.sqlite").airport_capacities()
    snapshot = load_snapshot("runway_closure_gate_conflict_v1", capacities=capacities)
    action = next(
        a
        for a in actions(snapshot)
        if a.gate_id == "B2"
        and a.landing_slot == snapshot.clock + timedelta(minutes=25)
        and a.approach_id == "standard"
        and a.taxi_path_id == "Bravo"
        and a.crew_id == "C2"
    )
    short = snapshot.model_copy(update={"turnaround_seconds": 44 * 60})
    report = evaluate(short, candidate(short, action))
    check = next(
        c for c in report.checks if c.constraint_id == "CAPACITY_MIN_TURNAROUND"
    )
    assert not check.passed
    assert capacities["DFW"].source_version in check.source_reference
    assert snapshot.destination.capacity.gates == 150
    # The airport-wide operations cap counts each modeled runway movement once,
    # rather than counting the separate arrival and runway reservations twice.
    limited = snapshot.destination.capacity.model_copy(
        update={"max_runway_ops_per_hour": 1}
    )
    tight = snapshot.model_copy(
        update={
            "destination": snapshot.destination.model_copy(update={"capacity": limited})
        }
    )
    report = evaluate(tight, candidate(tight, action))
    assert not next(
        c for c in report.checks if c.constraint_id == "CAPACITY_RUNWAY_OPERATIONS"
    ).passed


@pytest.mark.parametrize(
    "rows",
    [
        [{"airport": "DFW", "gate_id": "B2", "start_min": 30, "end_min": 30}],
        [{"airport": "DFW", "gate_id": "B2", "start_min": -1, "end_min": 30}],
        [
            {"airport": "DFW", "gate_id": "B2", "start_min": 0, "end_min": 30},
            {"airport": "DFW", "gate_id": "B2", "start_min": 29, "end_min": 40},
        ],
    ],
)
def test_invalid_gate_intervals_fail_before_run(rows):
    with pytest.raises(ValueError):
        RunRequest(gate_occupancies=rows)


def test_http_capacity_lookup_and_gate_inputs(tmp_path):
    from tests.test_blueprint_api import finished

    with TestClient(create_app(tmp_path / "api.sqlite")) as client:
        response = client.get("/airport-capacities/DFW")
        assert response.status_code == 200
        assert response.json()["min_turnaround_min"] == 45
        assert client.get("/airport-capacities/ZZZ").status_code == 404
        for gate in ("unknown", "B2"):
            payload = {
                "mode": "stub",
                "gate_occupancies": [
                    {"airport": "DFW", "gate_id": gate, "start_min": 0, "end_min": 120}
                ],
            }
            response = client.post(
                "/runs", json=payload, headers={"Idempotency-Key": gate}
            )
            if gate == "unknown":
                assert response.status_code == 422
                continue
            assert response.status_code == 202
            state = finished(client, response.json()["run_id"])
            assert state["status"] in ("CONSENSUS", "FALLBACK")
            assert state["result"]["selected_plan"]["action"]["gate_id"] != "B2"
            events = client.get(state["result"]["audit_event_reference"]).json()
            prepared = next(
                e["payload"]["snapshot"] for e in events if e["kind"] == "PREPARED"
            )
            assert prepared["destination"]["capacity"]["gates"] == 150
            assert any(
                r["resource"] == "gate:DFW:B2"
                and r["flight_id"].startswith("USER_GATE_")
                for r in prepared["reservations"]
            )
