"""Load versioned operational fixtures and build bounded action catalogues."""

from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

from .ingestion import normalize
from .schemas import Action, CandidatePlan, Snapshot, WorkflowInput, digest

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_snapshot(scenario_id: str, trigger: WorkflowInput | None = None) -> Snapshot:
    base = Snapshot.model_validate_json(
        (DATA_DIR / "scenarios/blueprint_v1.json").read_bytes()
    )
    payload = base.model_dump(mode="json")
    if trigger:
        flight = normalize(trigger)
        if flight.destination_airport != base.destination.iata_code:
            raise ValueError("NO_SUPPORTED_DEMO_ROW")
        anchor = flight.earliest_touchdown - timedelta(minutes=20)
        delta = anchor - base.clock

        def shift(value):
            if isinstance(value, dict):
                return {key: shift(item) for key, item in value.items()}
            if isinstance(value, list):
                return [shift(item) for item in value]
            if isinstance(value, str) and "T" in value:
                try:
                    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if stamp.tzinfo:
                        return (stamp + delta).isoformat()
                except ValueError:
                    pass
            return value

        payload = shift(payload)
        payload["flight_id"] = flight.flight_id
        payload["aircraft"]["tail_number"] = flight.tail_number
        payload["aircraft"]["mapping_source"] = "scenario_override"
        payload["operational_provenance"]["aircraft"] = (
            "scenario_override: explicit mock aircraft profile, not inferred from the tail or airline; kg, kg/min, knots"
        )
        payload["destination"]["lookup"] = next(
            a for a in trigger.airport_rows if a.IATA_CODE == flight.destination_airport
        ).model_dump(mode="json")
        alternate = trigger.provenance.raw_lookups.get("alternate")
        if (
            alternate is None
            or alternate.get("IATA_CODE") != payload["alternates"][0]["iata_code"]
        ):
            raise ValueError("ALTERNATE_LOOKUP_REQUIRED")
        payload["alternates"][0]["lookup"] = alternate
    payload["scenario_id"] = scenario_id
    payload["environment_id"] = digest(
        {
            "scenario": scenario_id,
            "clock": payload["clock"],
            "profile": base.profile_version,
        }
    )[:24]
    if scenario_id == "insufficient_fuel":
        payload["aircraft"]["fuel_kg"] = 4300
    elif scenario_id == "no_gate":
        for airport in [payload["destination"], *payload["alternates"]]:
            for gate in airport["gates"]:
                gate["aircraft_classes"] = ["UNSUPPORTED"]
    elif scenario_id == "diversion":
        airport = payload["destination"]
        for runway in airport["runways"]:
            runway["closed"] = [
                {"start": payload["clock"], "end": payload["valid_until"]}
            ]
    elif scenario_id != "runway_closure_gate_conflict_v1":
        raise ValueError("UNKNOWN_SCENARIO")
    return Snapshot.model_validate(payload)


def candidate(snapshot: Snapshot, action: Action, proposers=()) -> CandidatePlan:
    key = digest(
        {
            "action": action.model_dump(mode="json"),
            "schema": snapshot.schema_version,
            "profile": snapshot.profile_version,
            "policy": snapshot.policy.model_dump(mode="json"),
            "snapshot": snapshot.snapshot_version,
        }
    )
    return CandidatePlan(
        candidate_id=key[:20],
        plan_hash=key,
        snapshot_version=snapshot.snapshot_version,
        action=action,
        proposers=tuple(sorted(proposers)),
    )


def actions(snapshot: Snapshot, alternate: bool = False):
    airports = snapshot.alternates if alternate else (snapshot.destination,)
    for airport in airports:
        combinations = (
            len(airport.slots)
            * len(airport.approaches)
            * len(airport.paths)
            * len(airport.gates)
            * len(airport.crews)
        )
        if combinations > 1440:
            raise ValueError("CATALOGUE_BOUND_EXCEEDED")
        for slot, approach, path, gate, crew in product(
            sorted(airport.slots),
            airport.approaches,
            airport.paths,
            airport.gates,
            airport.crews,
        ):
            # Structural compatibility is catalogue membership, not a substitute for hard checks.
            if path.gate_id != gate.id or path.runway_id not in approach.runway_ids:
                continue
            yield Action(
                action="DIVERT" if alternate else "LAND",
                airport=airport.iata_code,
                landing_slot=slot,
                approach_id=approach.id,
                taxi_path_id=path.id,
                gate_id=gate.id,
                crew_id=crew.id,
            )


def catalogue(snapshot: Snapshot) -> dict:
    a = snapshot.destination
    return {
        "snapshot_version": snapshot.snapshot_version,
        "airport": a.iata_code,
        "landing_slots": [s.isoformat() for s in sorted(a.slots)],
        "approach_options": [v.model_dump(mode="json") for v in a.approaches],
        "taxi_paths": [v.model_dump(mode="json") for v in a.paths],
        "gate_ids": [g.id for g in a.gates],
        "crew_ids": [c.id for c in a.crews],
    }


def demo_clock() -> datetime:
    return datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
