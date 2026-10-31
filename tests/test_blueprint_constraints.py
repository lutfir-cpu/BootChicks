from datetime import timedelta

import pytest
from pydantic import ValidationError

from bootchicks.constraints import evaluate, fairness_rank, peak
from bootchicks.scenario import actions, candidate, load_snapshot
from bootchicks.schemas import Reservation, Snapshot, Window


@pytest.fixture
def snapshot():
    return load_snapshot("runway_closure_gate_conflict_v1")


def action_at(s, minute=25, gate="B2", path="Bravo", crew="C2"):
    return next(
        a
        for a in actions(s)
        if a.landing_slot == s.clock + timedelta(minutes=minute)
        and a.gate_id == gate
        and a.taxi_path_id == path
        and a.crew_id == crew
        and a.approach_id == "standard"
    )


def report(s, **kwargs):
    return evaluate(s, candidate(s, action_at(s, **kwargs)))


def failed(e):
    return {c.constraint_id for c in e.checks if not c.passed}


def airport_change(s, **updates):
    return s.model_copy(
        update={"destination": s.destination.model_copy(update=updates)}
    )


def test_worked_fixture_arithmetic(snapshot):
    e = report(snapshot)
    assert e.feasible
    assert e.outcomes.holding_min == 5
    assert e.outcomes.fuel_touchdown_kg == 4600
    assert e.outcomes.fuel_gate_kg == 4400
    assert e.outcomes.missed_connections == 0
    assert e.outcomes.overtime_min == 0
    baseline = report(snapshot, minute=35, gate="A1", path="Charlie", crew="C1")
    assert baseline.feasible
    assert baseline.outcomes.fuel_touchdown_kg == 4200
    assert baseline.outcomes.fuel_gate_kg == 4000
    assert baseline.outcomes.missed_connections == 20
    assert baseline.outcomes.overtime_min == 8


@pytest.mark.parametrize("fuel,valid", [(5400, True), (5399.9, False)])
def test_fuel_boundaries(snapshot, fuel, valid):
    s = snapshot.model_copy(
        update={"aircraft": snapshot.aircraft.model_copy(update={"fuel_kg": fuel})}
    )
    e = report(s)
    assert e.feasible == valid
    if not valid:
        assert {"LANDING_FUEL", "ON_BLOCK_FUEL"} <= failed(e)


def test_closed_runway_and_taxi(snapshot):
    assert "RUNWAY_OPEN" in failed(report(snapshot, minute=20))
    assert "TAXI_OPEN_0" in failed(report(snapshot, path="Alpha"))
    bad = report(snapshot, minute=45)
    assert {"LANDING_FUEL", "ON_BLOCK_FUEL"} <= failed(bad)
    with pytest.raises(ValueError):
        fairness_rank(bad)


def test_closure_during_occupancy(snapshot):
    runway = snapshot.destination.runways[0]
    closed = Window(
        start=snapshot.clock + timedelta(minutes=26),
        end=snapshot.clock + timedelta(minutes=27),
    )
    s = airport_change(
        snapshot,
        runways=(
            runway.model_copy(update={"closed": (closed,)}),
            *snapshot.destination.runways[1:],
        ),
    )
    assert "RUNWAY_OPEN" in failed(report(s))


@pytest.mark.parametrize("seconds,valid", [(120, True), (119, False)])
def test_ordered_wake_boundary(snapshot, seconds, valid):
    at = snapshot.clock + timedelta(minutes=25) - timedelta(seconds=seconds)
    reservation = Reservation(
        resource="runway:DFW:R1",
        interval=Window(start=at, end=at + timedelta(seconds=30)),
        flight_id="OTHER",
    )
    s = snapshot.model_copy(update={"reservations": (reservation,)})
    assert ("WAKE_BEFORE" not in failed(report(s))) == valid


def test_wake_direction_and_missing_policy_fail_closed(snapshot):
    at = snapshot.clock + timedelta(minutes=23)
    other = Reservation(
        resource="runway:DFW:R1",
        interval=Window(start=at, end=at + timedelta(seconds=30)),
        flight_id="HEAVY",
        wake_class="H",
    )
    s = snapshot.model_copy(update={"reservations": (other,)})
    assert "WAKE_BEFORE" in failed(report(s))
    assert "WAKE_BEFORE" in failed(
        report(airport_change(snapshot, wake_separation_seconds={}))
    )


@pytest.mark.parametrize("offset,valid", [(-35, True), (-35 + 1 / 60, False)])
def test_rolling_hour_boundary(snapshot, offset, valid):
    at = snapshot.clock + timedelta(minutes=offset)
    booking = Reservation(
        resource="arrival:DFW",
        interval=Window(start=at, end=at + timedelta(seconds=1)),
        flight_id="BOUNDARY",
    )
    s = airport_change(snapshot, rolling_arrival_limit=2).model_copy(
        update={"reservations": snapshot.reservations + (booking,)}
    )
    assert ("ROLLING_ARRIVAL_CAPACITY" not in failed(report(s))) == valid


def test_resource_capacity_sweep_handles_disjoint_intervals(snapshot):
    t = snapshot.clock
    interval = Window(start=t, end=t + timedelta(minutes=4))
    reservations = [
        Reservation(
            resource="edge",
            interval=Window(
                start=t + timedelta(minutes=i), end=t + timedelta(minutes=i + 1)
            ),
            flight_id=str(i),
        )
        for i in [0, 2]
    ]
    assert peak(interval, reservations) == 2


@pytest.mark.parametrize(
    "resource,rule",
    [
        ("taxi:DFW:trunk", "TAXI_CAPACITY_0"),
        ("gate:DFW:B2", "GATE_BOOKING"),
        ("crew:DFW:C2", "CREW_BOOKING"),
        ("sector:DFW", "SECTOR_CAPACITY"),
    ],
)
def test_existing_bookings_are_never_moved(snapshot, resource, rule):
    start = (
        15
        if resource.startswith("sector")
        else 25
        if resource.startswith("taxi")
        else 77
    )
    interval = Window(
        start=snapshot.clock + timedelta(minutes=start),
        end=snapshot.clock + timedelta(minutes=start + 2),
    )
    booking = Reservation(resource=resource, interval=interval, flight_id="FIXED")
    s = airport_change(snapshot, sector_capacity=1).model_copy(
        update={"reservations": snapshot.reservations + (booking,)}
    )
    assert rule in failed(report(s))
    assert s.reservations[-1] == booking


def test_gate_full_interval_and_half_open_endpoint(snapshot):
    t = snapshot.clock

    def booking(start):
        return Reservation(
            resource="gate:DFW:B2",
            interval=Window(
                start=t + timedelta(minutes=start), end=t + timedelta(minutes=start + 2)
            ),
            flight_id="OTHER",
        )

    assert "GATE_BOOKING" in failed(
        report(snapshot.model_copy(update={"reservations": (booking(77),)}))
    )
    assert "GATE_BOOKING" not in failed(
        report(snapshot.model_copy(update={"reservations": (booking(78),)}))
    )


@pytest.mark.parametrize("maximum,valid", [(480, True), (479, False)])
def test_crew_overtime_boundary(snapshot, maximum, valid):
    crew = snapshot.destination.crews[0].model_copy(
        update={"max_overtime_seconds": maximum}
    )
    s = airport_change(snapshot, crews=(crew, *snapshot.destination.crews[1:]))
    assert (
        "CREW_MAX_OVERTIME"
        not in failed(report(s, minute=35, gate="A1", path="Charlie", crew="C1"))
    ) == valid


def test_wind_turbulence_and_stale_identity(snapshot):
    s = snapshot.model_copy(
        update={
            "aircraft": snapshot.aircraft.model_copy(
                update={"crosswind_limit_knots": 7, "turbulence_limit": 0}
            )
        }
    )
    assert {"CROSSWIND", "TURBULENCE"} <= failed(report(s))
    p = candidate(snapshot, action_at(snapshot))
    assert "EXACT_PLAN_IDENTITY" in failed(
        evaluate(snapshot.model_copy(update={"version": 2}), p)
    )


def test_catalogue_bound_and_missing_critical_field(snapshot):
    payload = snapshot.model_dump(mode="json")
    payload["destination"]["slots"] = [
        (snapshot.clock + timedelta(minutes=i)).isoformat() for i in range(21)
    ]
    with pytest.raises(ValidationError):
        Snapshot.model_validate(payload)
    payload = snapshot.model_dump(mode="json")
    del payload["aircraft"]["protected_landing_kg"]
    with pytest.raises(ValidationError):
        Snapshot.model_validate(payload)
