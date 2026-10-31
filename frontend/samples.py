"""Synthetic cases: no claim to reconstruct historical operational conditions."""

from models import Gate, Interval, Runway, Scenario


def bundled_scenarios() -> dict[str, Scenario]:
    base = Scenario(
        name="Gate change after runway closure",
        flight_id="DEMO-1",
        fuel_remaining_kg=4500,
        remaining_plan_fuel_kg=3200,
        fuel_buffer_kg=300,
        holding_burn_kg_min=50,
        runways=(Runway(id="SIM-RWY1", closed=(Interval(start=8, end=20),)),),
        gates=(Gate(id="G1", occupied=(Interval(start=0, end=40),)), Gate(id="G2")),
        provenance={
            "flight_metadata": "Synthetic example",
            "fuel": "Assumed",
            "runway_geometry_and_rules": "Assumed simulation resources, not published operational minima",
            "closures_and_reservations": "Assumed",
            "gate_and_handling": "Assumed",
            "taxi_and_turnaround": "Assumed",
        },
    )
    return {
        base.name: base,
        "Insufficient fuel": base.model_copy(
            update={"name": "Insufficient fuel", "fuel_remaining_kg": 3700}
        ),
        "No compatible gate": base.model_copy(
            update={
                "name": "No compatible gate",
                "gates": (
                    Gate(id="G1", compatible=False),
                    Gate(id="G2", compatible=False),
                ),
            }
        ),
    }
