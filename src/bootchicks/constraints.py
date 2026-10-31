"""Authoritative simulation arithmetic; LLM assertions never determine feasibility."""

from datetime import timedelta

from .capacity import rolling_operations
from .scenario import candidate
from .schemas import (
    CandidateEvaluation,
    CandidatePlan,
    CheckResult,
    Outcomes,
    Reservation,
    Snapshot,
    Window,
)


def overlaps(a: Window, b: Window) -> bool:
    return a.start < b.end and b.start < a.end


def covered(interval: Window, available) -> bool:
    return any(w.start <= interval.start and interval.end <= w.end for w in available)


def peak(interval: Window, reservations) -> int:
    points = [(interval.start, 1), (interval.end, -1)]
    for r in reservations:
        if overlaps(interval, r.interval):
            points.extend(
                [
                    (max(interval.start, r.interval.start), 1),
                    (min(interval.end, r.interval.end), -1),
                ]
            )
    active = maximum = 0
    for _, change in sorted(points, key=lambda p: (p[0], p[1])):
        active += change
        maximum = max(maximum, active)
    return maximum


def evaluate(s: Snapshot, p: CandidatePlan) -> CandidateEvaluation:
    checks: list[CheckResult] = []

    def add(key, domain, ok, measured, bound, unit="boolean", margin=None, source=None):
        checks.append(
            CheckResult(
                constraint_id=key,
                domain=domain,
                passed=bool(ok),
                measured=measured,
                bound=bound,
                unit=unit,
                margin=margin,
                source_reference=source
                or f"{s.profile_version}/{s.policy.version}/{key}; mock_fixture; {s.snapshot_version}",
            )
        )

    expected = candidate(s, p.action)
    add(
        "EXACT_PLAN_IDENTITY",
        "ATC",
        p.snapshot_version == s.snapshot_version
        and p.plan_hash == expected.plan_hash
        and p.candidate_id == expected.candidate_id,
        p.plan_hash,
        expected.plan_hash,
        "sha256",
    )
    add(
        "FLIGHT_NOT_ALREADY_COMMITTED",
        "ATC",
        not any(r.flight_id == s.flight_id for r in s.reservations),
        any(r.flight_id == s.flight_id for r in s.reservations),
        False,
    )
    a = p.action
    airports = (s.destination,) if a.action == "LAND" else s.alternates
    airport = next((v for v in airports if v.iata_code == a.airport), None)
    add(
        "AIRPORT_ALLOWED",
        "ATC",
        airport is not None,
        a.airport,
        s.destination.iata_code if a.action == "LAND" else "configured alternate",
        "id",
    )
    if airport is None:
        return CandidateEvaluation(
            candidate=p,
            feasible=False,
            checks=tuple(checks),
            outcomes=None,
            domain_costs={},
            reservations=(),
        )
    runway = next(
        (
            r
            for r in airport.runways
            if r.id
            in next(
                (v.runway_ids for v in airport.approaches if v.id == a.approach_id), ()
            )
        ),
        None,
    )
    path = next((v for v in airport.paths if v.id == a.taxi_path_id), None)
    approach = next((v for v in airport.approaches if v.id == a.approach_id), None)
    gate = next((v for v in airport.gates if v.id == a.gate_id), None)
    crew = next((v for v in airport.crews if v.id == a.crew_id), None)
    if path:
        runway = next((r for r in airport.runways if r.id == path.runway_id), None)
    for key, domain, value in (
        ("RUNWAY_EXISTS", "ATC", runway),
        ("PATH_EXISTS", "ATC", path),
        ("APPROACH_EXISTS", "PILOT", approach),
        ("GATE_EXISTS", "GROUND", gate),
        ("CREW_EXISTS", "GROUND", crew),
    ):
        add(key, domain, value is not None, value is not None, True)
    if any(v is None for v in (runway, path, approach, gate, crew)):
        return CandidateEvaluation(
            candidate=p,
            feasible=False,
            checks=tuple(checks),
            outcomes=None,
            domain_costs={},
            reservations=(),
        )
    aircraft = s.aircraft
    touchdown = a.landing_slot
    approach_end_earliest = s.clock + timedelta(seconds=approach.duration_seconds)
    hold = (touchdown - approach_end_earliest).total_seconds() / 60
    operation = Window(
        start=touchdown, end=touchdown + timedelta(seconds=runway.occupancy_seconds)
    )
    add(
        "CATALOGUE_SLOT",
        "ATC",
        touchdown in airport.slots,
        touchdown.isoformat(),
        "configured landing slot",
        "UTC",
    )
    add("APPROACH_FEASIBLE", "PILOT", hold >= 0, hold, 0, "min", hold)
    add(
        "RUNWAY_OPEN",
        "ATC",
        not any(overlaps(operation, w) for w in runway.closed),
        not any(overlaps(operation, w) for w in runway.closed),
        True,
    )
    add(
        "RUNWAY_CLASS",
        "ATC",
        aircraft.gate_class in runway.aircraft_classes,
        aircraft.gate_class,
        ",".join(runway.aircraft_classes),
        "class",
    )
    add(
        "APPROACH_COMPATIBILITY",
        "ATC",
        approach.id in runway.approach_ids and runway.id in approach.runway_ids,
        approach.id,
        ",".join(runway.approach_ids),
        "id",
    )
    add(
        "CROSSWIND",
        "PILOT",
        runway.crosswind_knots <= aircraft.crosswind_limit_knots,
        runway.crosswind_knots,
        aircraft.crosswind_limit_knots,
        "knots",
        aircraft.crosswind_limit_knots - runway.crosswind_knots,
    )
    add(
        "TURBULENCE",
        "PILOT",
        approach.turbulence <= aircraft.turbulence_limit,
        approach.turbulence,
        aircraft.turbulence_limit,
        "ordinal",
        aircraft.turbulence_limit - approach.turbulence,
    )
    approach_window = Window(
        start=touchdown - timedelta(seconds=approach.duration_seconds), end=touchdown
    )
    add(
        "WEATHER_VALIDITY",
        "PILOT",
        covered(approach_window, (approach.valid,))
        and covered(operation, (runway.weather_valid,)),
        touchdown.isoformat(),
        "weather and approach intervals cover operation",
        "UTC",
    )
    resource_prefix = f"{airport.iata_code}:"
    bookings = []
    capacity = airport.capacity
    if capacity:
        source = f"airport_capacity/{capacity.iata_code}/{capacity.source_version}; sha256:{capacity.source_sha256}; challenge_synthetic"
        for key, owner, measured, bound, unit in (
            (
                "CAPACITY_ACTIVE_RUNWAYS",
                "ATC",
                len(airport.runways),
                capacity.active_runways,
                "modeled runway count",
            ),
            (
                "CAPACITY_GATE_TOTAL",
                "GROUND",
                len(airport.gates),
                capacity.gates,
                "modeled gate count",
            ),
        ):
            add(
                key,
                owner,
                measured <= bound,
                measured,
                bound,
                unit,
                bound - measured,
                source=source,
            )
        minimum = capacity.min_turnaround_min * 60
        add(
            "CAPACITY_MIN_TURNAROUND",
            "GROUND",
            s.turnaround_seconds >= minimum,
            s.turnaround_seconds,
            minimum,
            "seconds",
            s.turnaround_seconds - minimum,
            source=source,
        )
        operations = rolling_operations(
            [
                r.interval.start.timestamp()
                for r in s.reservations
                if r.resource.startswith(f"runway:{resource_prefix}")
            ],
            touchdown.timestamp(),
        )
        add(
            "CAPACITY_RUNWAY_OPERATIONS",
            "ATC",
            operations <= capacity.max_runway_ops_per_hour,
            operations,
            capacity.max_runway_ops_per_hour,
            "modeled operations / rolling 60 min",
            capacity.max_runway_ops_per_hour - operations,
            source=source,
        )

    def reserve(kind, ident, interval, capacity, owner, key):
        resource = (
            f"{kind}:{resource_prefix}{ident}"
            if ident
            else f"{kind}:{airport.iata_code}"
        )
        existing = [r for r in s.reservations if r.resource == resource]
        used = peak(interval, existing)
        add(
            key,
            owner,
            used <= capacity,
            used,
            capacity,
            "concurrent resources",
            capacity - used,
        )
        bookings.append(
            Reservation(
                resource=resource,
                interval=interval,
                flight_id=s.flight_id,
                wake_class=aircraft.wake_class,
            )
        )

    reserve("runway", runway.id, operation, 1, "ATC", "RUNWAY_OCCUPANCY")
    movements = sorted(
        (
            r
            for r in s.reservations
            if r.resource == f"runway:{resource_prefix}{runway.id}"
        ),
        key=lambda r: r.interval.start,
    )
    previous = [r for r in movements if r.interval.start <= touchdown]
    following = [r for r in movements if r.interval.start > touchdown]
    for key, other, leader, follower in (
        (
            "WAKE_BEFORE",
            previous[-1] if previous else None,
            previous[-1].wake_class if previous else aircraft.wake_class,
            aircraft.wake_class,
        ),
        (
            "WAKE_AFTER",
            following[0] if following else None,
            aircraft.wake_class,
            following[0].wake_class if following else aircraft.wake_class,
        ),
    ):
        required = airport.wake_separation_seconds.get(leader, {}).get(follower)
        gap = abs((touchdown - other.interval.start).total_seconds()) if other else None
        add(
            key,
            "ATC",
            required is not None and (gap is None or gap >= required),
            gap,
            required,
            "seconds",
            gap - required if gap is not None and required is not None else None,
        )
    arrivals = [
        r.interval.start
        for r in s.reservations
        if r.resource == f"arrival:{airport.iata_code}"
    ] + [touchdown]
    maximum = max(
        sum(start <= t < start + timedelta(hours=1) for t in arrivals)
        for start in arrivals
        if start <= touchdown < start + timedelta(hours=1)
    )
    add(
        "ROLLING_ARRIVAL_CAPACITY",
        "ATC",
        maximum <= airport.rolling_arrival_limit,
        maximum,
        airport.rolling_arrival_limit,
        "arrivals / rolling 60 min",
        airport.rolling_arrival_limit - maximum,
    )
    bookings.append(
        Reservation(
            resource=f"arrival:{airport.iata_code}",
            interval=operation,
            flight_id=s.flight_id,
            wake_class=aircraft.wake_class,
        )
    )
    sector = Window(
        start=touchdown - timedelta(seconds=airport.sector_seconds), end=touchdown
    )
    reserve("sector", "", sector, airport.sector_capacity, "ATC", "SECTOR_CAPACITY")
    cursor, node, taxi_seconds = touchdown, runway.id, 0
    path_valid = path.gate_id == gate.id and path.runway_id == runway.id
    for index, edge_id in enumerate(path.edge_ids):
        edge = next((e for e in airport.edges if e.id == edge_id), None)
        add(
            f"TAXI_EDGE_EXISTS_{index}",
            "ATC",
            edge is not None,
            edge_id,
            "configured edge",
            "id",
        )
        if edge is None:
            path_valid = False
            continue
        path_valid = path_valid and node == edge.start_node
        interval = Window(
            start=cursor, end=cursor + timedelta(seconds=edge.duration_seconds)
        )
        add(
            f"TAXI_OPEN_{index}",
            "ATC",
            not any(overlaps(interval, w) for w in edge.closed),
            edge.id,
            "open during traversal",
            "id",
        )
        reserve(
            "taxi", edge.id, interval, edge.capacity, "ATC", f"TAXI_CAPACITY_{index}"
        )
        cursor, node = interval.end, edge.end_node
        taxi_seconds += edge.duration_seconds
    path_valid = path_valid and node == gate.id
    add("TAXI_CONNECTED", "ATC", path_valid, f"{runway.id} to {node}", gate.id, "id")
    gate_arrival = cursor
    service_end = gate_arrival + timedelta(seconds=s.turnaround_seconds)
    gate_window = Window(
        start=gate_arrival - timedelta(seconds=gate.buffer_seconds),
        end=service_end + timedelta(seconds=gate.buffer_seconds),
    )
    crew_window = Window(start=gate_arrival, end=service_end)
    add(
        "GATE_COMPATIBLE",
        "GROUND",
        aircraft.gate_class in gate.aircraft_classes
        and set(aircraft.required_services) <= set(gate.services),
        aircraft.gate_class,
        ",".join(gate.aircraft_classes),
        "class/services",
    )
    add(
        "GATE_AVAILABILITY",
        "GROUND",
        covered(gate_window, gate.available),
        gate_arrival.isoformat(),
        "entire occupancy including buffer",
        "UTC",
    )
    reserve("gate", gate.id, gate_window, 1, "GROUND", "GATE_BOOKING")
    if capacity and (a.action == "DIVERT" or gate.id != s.preferred_gate):
        spare = [
            r for r in s.reservations if r.resource == f"spare_gate:{airport.iata_code}"
        ]
        used = peak(gate_window, spare)
        add(
            "CAPACITY_SPARE_GATES",
            "GROUND",
            used <= capacity.spare_gates_at_any_time,
            used,
            capacity.spare_gates_at_any_time,
            "concurrent reassigned/diverted gate allocations",
            capacity.spare_gates_at_any_time - used,
            source=source,
        )
        bookings.append(
            Reservation(
                resource=f"spare_gate:{airport.iata_code}",
                interval=gate_window,
                flight_id=s.flight_id,
                wake_class=aircraft.wake_class,
            )
        )
    add(
        "CREW_SKILLS",
        "GROUND",
        set(aircraft.required_services) <= set(crew.skills)
        and gate.id in crew.gate_ids,
        crew.id,
        "skills and gate assignment match",
        "id",
    )
    add(
        "CREW_AVAILABILITY",
        "GROUND",
        covered(crew_window, crew.available),
        crew.id,
        "entire service interval available",
        "id",
    )
    overtime_seconds = max(0, (service_end - crew.shift_end).total_seconds())
    add(
        "CREW_MAX_OVERTIME",
        "GROUND",
        overtime_seconds <= crew.max_overtime_seconds,
        overtime_seconds,
        crew.max_overtime_seconds,
        "seconds",
        crew.max_overtime_seconds - overtime_seconds,
    )
    reserve("crew", crew.id, crew_window, 1, "GROUND", "CREW_BOOKING")
    add(
        "SNAPSHOT_VALIDITY",
        "ATC",
        s.clock <= touchdown and gate_window.end <= s.valid_until,
        gate_window.end.isoformat(),
        s.valid_until.isoformat(),
        "UTC",
        (s.valid_until - gate_window.end).total_seconds(),
    )
    fuel_touchdown = (
        aircraft.fuel_kg - approach.burn_kg - max(0, hold) * aircraft.hold_burn_kg_min
    )
    fuel_gate = fuel_touchdown - taxi_seconds / 60 * aircraft.taxi_burn_kg_min
    add(
        "LANDING_FUEL",
        "PILOT",
        fuel_touchdown >= aircraft.protected_landing_kg,
        fuel_touchdown,
        aircraft.protected_landing_kg,
        "kg",
        fuel_touchdown - aircraft.protected_landing_kg,
    )
    add(
        "ON_BLOCK_FUEL",
        "PILOT",
        fuel_gate >= aircraft.protected_on_block_kg,
        fuel_gate,
        aircraft.protected_on_block_kg,
        "kg",
        fuel_gate - aircraft.protected_on_block_kg,
    )
    missed = total = 0
    for connection in s.connections:
        total += connection.passengers
        transfer = connection.transfer_seconds_by_gate.get(gate.id)
        if (
            a.action == "DIVERT"
            or transfer is None
            or gate_arrival + timedelta(seconds=transfer) > connection.boarding_deadline
        ):
            missed += connection.passengers
    outcomes = Outcomes(
        touchdown=touchdown,
        gate_arrival=gate_arrival,
        service_end=service_end,
        holding_min=max(0, hold),
        airborne_fuel_kg=approach.burn_kg + max(0, hold) * aircraft.hold_burn_kg_min,
        fuel_touchdown_kg=fuel_touchdown,
        fuel_gate_kg=fuel_gate,
        landing_margin_kg=fuel_touchdown - aircraft.protected_landing_kg,
        gate_margin_kg=fuel_gate - aircraft.protected_on_block_kg,
        taxi_min=taxi_seconds / 60,
        gate_wait_min=0,
        missed_connections=missed,
        missed_connection_fraction=missed / total if total else 0,
        overtime_min=overtime_seconds / 60,
        next_departure_delay_min=max(
            0, (service_end - s.next_departure_target).total_seconds() / 60
        ),
    )
    scales = s.policy.scales

    def norm(value, name):
        return min(1, max(0, value / scales[name]))

    def weighted(values, weights):
        return sum(
            value * weight for value, weight in zip(values, weights, strict=True)
        )

    costs = {
        "ATC": weighted(
            (
                norm(outcomes.holding_min, "delay_min"),
                norm(outcomes.taxi_min, "taxi_min"),
            ),
            s.policy.atc_weights,
        ),
        "PILOT": weighted(
            (
                norm(outcomes.airborne_fuel_kg, "airborne_fuel_kg"),
                outcomes.missed_connection_fraction,
            ),
            s.policy.pilot_weights,
        ),
        "GROUND": weighted(
            (
                norm(outcomes.gate_wait_min, "gate_wait_min"),
                norm(outcomes.overtime_min, "overtime_min"),
                norm(outcomes.next_departure_delay_min, "next_departure_delay_min"),
            ),
            s.policy.ground_weights,
        ),
    }
    return CandidateEvaluation(
        candidate=p,
        feasible=all(c.passed for c in checks),
        checks=tuple(checks),
        outcomes=outcomes,
        domain_costs=costs,
        reservations=tuple(bookings),
    )


def fairness_rank(evaluation: CandidateEvaluation):
    if not evaluation.feasible or not evaluation.outcomes:
        raise ValueError("Cannot rank a hard-failing candidate.")
    values = evaluation.domain_costs.values()
    return (
        max(values),
        sum(values),
        evaluation.outcomes.touchdown,
        evaluation.candidate.candidate_id,
    )


def fallback_rank(evaluation: CandidateEvaluation):
    o = evaluation.outcomes
    if not evaluation.feasible or o is None:
        raise ValueError("Cannot rank an infeasible fallback.")
    return (
        o.airborne_fuel_kg,
        o.touchdown,
        o.missed_connections,
        o.overtime_min,
        evaluation.candidate.candidate_id,
    )


def improvement(baseline, result):
    if (
        baseline is None
        or not baseline.feasible
        or result is None
        or not result.feasible
    ):
        return None
    b, r = baseline.outcomes, result.outcomes
    return {
        "holding_saved_min": b.holding_min - r.holding_min,
        "airborne_fuel_saved_kg": b.airborne_fuel_kg - r.airborne_fuel_kg,
        "earlier_gate_arrival_min": (b.gate_arrival - r.gate_arrival).total_seconds()
        / 60,
        "overtime_saved_min": b.overtime_min - r.overtime_min,
        "connections_saved": b.missed_connections - r.missed_connections,
    }
