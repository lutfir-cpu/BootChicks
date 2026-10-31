"""Load versioned operational fixtures and build bounded action catalogues."""

from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

from .ingestion import normalize
from .schemas import Action, CandidatePlan, RunRequest, Snapshot, WorkflowInput, digest

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SCENARIOS = {
    "runway_closure_gate_conflict_v1": {
        "label": "Runway closure and gate conflict",
        "description": "R1 is closed until 06:22 and R2 for the whole window. "
        "Ground prefers the assigned gate A1; ATC and Pilot prefer an earlier slot at B2.",
    },
    "insufficient_fuel": {
        "label": "Insufficient fuel",
        "description": "Fuel onboard is cut to 4,300 kg, below the protected floors for every option. "
        "Expect escalation for human review.",
    },
    "no_gate": {
        "label": "No compatible gate",
        "description": "No gate at DFW or the DAL alternate accepts this aircraft. "
        "Expect escalation for human review.",
    },
    "diversion": {
        "label": "Diversion to alternate",
        "description": "Every DFW runway is closed for the whole window. "
        "The deterministic fallback validates a diversion to DAL.",
    },
}


def load_snapshot(
    scenario_id: str,
    trigger: WorkflowInput | None = None,
    *,
    capacities=None,
    gate_occupancies=(),
    environment=None,
) -> Snapshot:
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
    if capacities is not None:
        for airport in [payload["destination"], *payload["alternates"]]:
            code = airport["iata_code"]
            if code not in capacities:
                raise ValueError(f"No challenge capacity data for {code}.")
            airport["capacity"] = capacities[code].model_dump(mode="json")
        payload["operational_provenance"]["airport_capacity"] = (
            "Challenge-provided SYNTHETIC planning limits; only modeled runway operations are counted. "
            "Named resources, closures, fuel, weather and crews remain scenario assumptions."
        )
    # Revalidate even when called directly, rather than trusting a prior request validation.
    occupancies = RunRequest(gate_occupancies=gate_occupancies).gate_occupancies
    airports = {
        a["iata_code"]: a for a in [payload["destination"], *payload["alternates"]]
    }
    clock = datetime.fromisoformat(payload["clock"].replace("Z", "+00:00"))
    for index, busy in enumerate(occupancies):
        airport = airports.get(busy.airport)
        if airport is None or busy.gate_id not in {g["id"] for g in airport["gates"]}:
            raise ValueError(
                f"Unknown gate {busy.airport}/{busy.gate_id} in this scenario."
            )
        payload["reservations"].append(
            {
                "resource": f"gate:{busy.airport}:{busy.gate_id}",
                "interval": {
                    "start": (clock + timedelta(minutes=busy.start_min)).isoformat(),
                    "end": (clock + timedelta(minutes=busy.end_min)).isoformat(),
                },
                "flight_id": f"USER_GATE_{index}",
                "wake_class": "M",
            }
        )
    if capacities is not None or occupancies or environment:
        identity = {
            "base_environment": payload["environment_id"],
            "capacity_rows": [a.get("capacity") for a in airports.values()],
            "gate_occupancies": [busy.model_dump(mode="json") for busy in occupancies],
        }
        if environment:
            identity["environment"] = environment
        payload["environment_id"] = digest(identity)[:24]
    if occupancies:
        payload["operational_provenance"]["gate_occupancies"] = (
            "User-defined half-open intervals, minutes relative to scenario clock; saved as UTC reservations."
        )
    return Snapshot.model_validate(payload)


def request_snapshot(request: RunRequest, capacities) -> Snapshot:
    return load_snapshot(
        request.trigger.scenario_id if request.trigger else request.scenario_id,
        request.trigger,
        capacities=capacities,
        gate_occupancies=request.gate_occupancies,
        environment=request.environment,
    )


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
