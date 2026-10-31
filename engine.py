"""Small, bounded coordinator. All mandatory checks are evaluated in Python."""

from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from models import (
    ROLES,
    AgentResponse,
    Candidate,
    Check,
    Interval,
    Result,
    Role,
    RoundRecord,
    Scenario,
)

HORIZON_MIN = 60


class Agent(Protocol):
    mode: str
    is_live: bool

    def evaluate(
        self,
        role: Role,
        scenario: Scenario,
        candidate: Candidate,
        checks: tuple[Check, ...],
        history: tuple[RoundRecord, ...],
    ) -> AgentResponse: ...


def overlaps(start: int, end: int, interval: Interval) -> bool:
    """Intervals are half-open: ending exactly at another start is permitted."""
    return start < interval.end and interval.start < end


def missing_inputs(s: Scenario) -> tuple[str, ...]:
    missing = [
        name
        for name in (
            "fuel_remaining_kg",
            "remaining_plan_fuel_kg",
            "fuel_buffer_kg",
            "holding_burn_kg_min",
        )
        if getattr(s, name) is None
    ]
    if not s.runways:
        missing.append("runways")
    if not s.gates:
        missing.append("gates")
    if s.gates and s.original_gate not in {g.id for g in s.gates}:
        missing.append("original_gate (must refer to a configured gate)")
    return tuple(missing)


def make_candidate(
    s: Scenario, landing: int, runway: str, gate: str, version: int
) -> Candidate:
    return Candidate(
        id=f"P{version}",
        version=version,
        state_version=s.state_version,
        runway_id=runway,
        landing_min=landing,
        gate_id=gate,
        gate_in_min=landing + s.taxi_min,
        gate_out_min=landing + s.taxi_min + s.turnaround_min,
    )


def validate(s: Scenario, p: Candidate) -> tuple[Check, ...]:
    checks = []

    def add(rule, role, passed, detail):
        checks.append(Check(rule_id=rule, role=role, passed=passed, detail=detail))

    add(
        "STATE_VERSION",
        "ATC",
        p.state_version == s.state_version,
        f"Plan state {p.state_version}; scenario state {s.state_version}.",
    )
    add(
        "ARRIVAL_WINDOW",
        "ATC",
        s.nominal_arrival_min <= p.landing_min <= s.nominal_arrival_min + HORIZON_MIN,
        f"Landing {p.landing_min}; replay window {s.nominal_arrival_min} to {s.nominal_arrival_min + HORIZON_MIN} min.",
    )
    runway = next((r for r in s.runways if r.id == p.runway_id), None)
    add(
        "RUNWAY_EXISTS",
        "ATC",
        runway is not None,
        f"Runway {p.runway_id} must be configured.",
    )
    if runway:
        finish = p.landing_min + runway.occupancy_min
        add(
            "RUNWAY_OPEN",
            "ATC",
            not any(overlaps(p.landing_min, finish, i) for i in runway.closed),
            f"Operation [{p.landing_min}, {finish}) must avoid closures.",
        )
        add(
            "RUNWAY_OCCUPANCY",
            "ATC",
            not any(overlaps(p.landing_min, finish, i) for i in runway.reservations),
            f"Operation [{p.landing_min}, {finish}) must avoid background reservations.",
        )
        add(
            "RUNWAY_SEPARATION",
            "ATC",
            all(
                abs(p.landing_min - i.start) >= runway.separation_min
                for i in runway.reservations
            ),
            f"Configured start-to-start gap is {runway.separation_min} min (simulation assumption).",
        )
    fuel_fields = (
        s.fuel_remaining_kg,
        s.remaining_plan_fuel_kg,
        s.fuel_buffer_kg,
        s.holding_burn_kg_min,
    )
    if any(value is None for value in fuel_fields):
        add(
            "FUEL_INPUTS",
            "Pilot",
            False,
            "Fuel inputs are incomplete; cannot validate.",
        )
    else:
        hold = max(0, p.landing_min - s.nominal_arrival_min)
        remaining = s.fuel_remaining_kg - hold * s.holding_burn_kg_min
        required = s.remaining_plan_fuel_kg + s.fuel_buffer_kg
        add(
            "FUEL_BUDGET",
            "Pilot",
            remaining >= required,
            f"Hold {hold} min; fuel after holding {remaining:.1f} kg; remaining-plan requirement + buffer {required:.1f} kg.",
        )
    add(
        "TAXI_TIMING",
        "Ground",
        p.gate_in_min == p.landing_min + s.taxi_min,
        f"Gate-in must equal landing + {s.taxi_min} min taxi.",
    )
    add(
        "TURNAROUND_TIMING",
        "Ground",
        p.gate_out_min == p.gate_in_min + s.turnaround_min,
        f"Gate occupancy must last {s.turnaround_min} min.",
    )
    gate = next((g for g in s.gates if g.id == p.gate_id), None)
    add(
        "GATE_EXISTS",
        "Ground",
        gate is not None,
        f"Gate {p.gate_id} must be configured.",
    )
    if gate:
        add(
            "GATE_COMPATIBLE",
            "Ground",
            gate.compatible,
            f"Gate {gate.id} compatibility: {gate.compatible}.",
        )
        add(
            "GATE_AVAILABLE",
            "Ground",
            not any(overlaps(p.gate_in_min, p.gate_out_min, i) for i in gate.occupied),
            f"Gate {gate.id} must be free throughout [{p.gate_in_min}, {p.gate_out_min}).",
        )
        add(
            "HANDLING_AVAILABLE",
            "Ground",
            gate.handling_available,
            f"Ground handling available at {gate.id}: {gate.handling_available}.",
        )
    return tuple(checks)


def candidate_options(s: Scenario, version: int):
    for landing in range(
        s.nominal_arrival_min, s.nominal_arrival_min + HORIZON_MIN + 1
    ):
        for runway in sorted(s.runways, key=lambda r: r.id):
            for gate in sorted(s.gates, key=lambda g: (g.id != s.original_gate, g.id)):
                yield make_candidate(s, landing, runway.id, gate.id, version)


def rank(s: Scenario, p: Candidate):
    return (
        p.landing_min - s.nominal_arrival_min,
        p.gate_id != s.original_gate,
        p.runway_id,
        p.gate_id,
    )


def feasible_candidates(s: Scenario, version: int) -> list[Candidate]:
    return sorted(
        (
            p
            for p in candidate_options(s, version)
            if all(c.passed for c in validate(s, p))
        ),
        key=lambda p: rank(s, p),
    )


def first_candidate(s: Scenario) -> Candidate | None:
    # Check ATC only here, preserving the need for cross-domain negotiation.
    for p in candidate_options(s, 1):
        if p.gate_id == s.original_gate and all(
            c.passed for c in validate(s, p) if c.role == "ATC"
        ):
            return p
    return None


def validate_response(role: Role, p: Candidate, response: AgentResponse) -> None:
    if (
        response.role,
        response.candidate_id,
        response.candidate_version,
        response.state_version,
    ) != (role, p.id, p.version, p.state_version):
        raise ValueError(
            "Response role or plan/state version does not match this candidate."
        )
    if response.decision == "ACCEPT" and (
        response.failed_rule_ids or response.proposed_changes is not None
    ):
        raise ValueError(
            "Acceptance cannot include failed rules or an unapproved plan change."
        )


def revised_candidate(
    s: Scenario, p: Candidate, responses: tuple[AgentResponse, ...]
) -> Candidate | None:
    proposals = []
    for response in responses:
        change = response.proposed_changes
        if response.decision != "COUNTER" or change is None:
            continue
        alternate = make_candidate(
            s,
            change.landing_min if change.landing_min is not None else p.landing_min,
            change.runway_id if change.runway_id is not None else p.runway_id,
            change.gate_id if change.gate_id is not None else p.gate_id,
            p.version + 1,
        )
        if all(c.passed for c in validate(s, alternate)):
            proposals.append(alternate)
    return min(proposals, key=lambda option: rank(s, option)) if proposals else None


def negotiate(s: Scenario, agent: Agent, max_rounds: int = 2) -> Result:
    if max_rounds not in (1, 2, 3):
        raise ValueError("Round limit must be 1, 2 or 3.")
    missing = missing_inputs(s)
    if missing:
        return Result(
            status="Missing information",
            reason="Complete mandatory scenario inputs before running.",
            scenario=s,
            mode=agent.mode,
            missing_fields=missing,
        )
    history: list[RoundRecord] = []
    api_count = 0
    candidate = first_candidate(s)
    reason = "No runway-feasible initial candidate in the replay window."
    for number in range(1, max_rounds + 1):
        if candidate is None:
            break
        checks = validate(s, candidate)
        responses, errors = [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {
                role: pool.submit(
                    agent.evaluate, role, s, candidate, checks, tuple(history)
                )
                for role in ROLES
            }
            api_count += 3 if agent.is_live else 0
            for role, job in jobs.items():
                try:
                    response = job.result()
                    validate_response(role, candidate, response)
                    responses.append(response)
                except Exception as exc:  # noqa: BLE001 - isolate external provider failures; fail closed.
                    # Never expose credentials, provider response bodies or raw exception messages.
                    errors.append(
                        f"{role}: {type(exc).__name__}; no approval recorded."
                    )
        record = RoundRecord(
            number=number,
            candidate=candidate,
            checks=checks,
            responses=tuple(responses),
            errors=tuple(errors),
        )
        history.append(record)
        counts = {
            "round_count": len(history),
            "agent_message_count": sum(len(r.responses) for r in history),
            "api_request_count": api_count,
        }
        if (
            len(responses) == 3
            and not errors
            and all(r.decision == "ACCEPT" for r in responses)
            and all(c.passed for c in checks)
        ):
            final_checks = validate(s, candidate)
            if all(c.passed for c in final_checks):
                return Result(
                    status="Agreed",
                    reason="All three roles accepted the same validated plan version.",
                    scenario=s,
                    mode=agent.mode,
                    plan=candidate,
                    rounds=tuple(history),
                    final_checks=final_checks,
                    **counts,
                )
        if errors:
            reason = "A role call failed or returned an invalid response. Negotiation stopped."
            break
        if any(r.decision == "NEED_INFORMATION" for r in responses):
            return Result(
                status="Missing information",
                reason="An agent requested additional evidence; no plan approved.",
                scenario=s,
                mode=agent.mode,
                rounds=tuple(history),
                **counts,
            )
        reason = "Negotiation budget exhausted without unanimous validated agreement."
        if number < max_rounds:
            revised = revised_candidate(s, candidate, tuple(responses))
            if revised is None:
                reason = "No valid counterproposal was supplied. Negotiation stopped."
                break
            if (revised.landing_min, revised.runway_id, revised.gate_id) == (
                candidate.landing_min,
                candidate.runway_id,
                candidate.gate_id,
            ):
                reason = (
                    "Counterproposal repeated the current plan. Negotiation stopped."
                )
                break
            candidate = revised
    options = feasible_candidates(s, len(history) + 1)
    plan = options[0] if options else None
    return Result(
        status="Fallback recommendation" if plan else "No feasible plan",
        reason=reason
        + (
            " A deterministic feasible option is shown; it has no negotiated approval."
            if plan
            else " No feasible option was found within the 60-minute search horizon."
        ),
        scenario=s,
        mode=agent.mode,
        plan=plan,
        rounds=tuple(history),
        final_checks=validate(s, plan) if plan else (),
        round_count=len(history),
        agent_message_count=sum(len(r.responses) for r in history),
        api_request_count=api_count,
    )
