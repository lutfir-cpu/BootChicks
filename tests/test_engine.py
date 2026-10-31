import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agents import ClaudeAgents, SimulatedAgents
from engine import make_candidate, negotiate, validate
from models import AgentResponse, Gate, Interval, ProposedChanges, Runway, Scenario
from samples import bundled_scenarios


@pytest.fixture
def scenario():
    return next(iter(bundled_scenarios().values()))


def fails(scenario, candidate):
    return {c.rule_id for c in validate(scenario, candidate) if not c.passed}


def test_success_requires_gate_counterproposal(scenario):
    result = negotiate(scenario, SimulatedAgents())
    assert result.status == "Agreed"
    assert result.round_count == 2
    assert result.agent_message_count == 6
    assert result.api_request_count == 0
    assert result.plan.gate_id == "G2"
    assert result.plan.landing_min == 20
    assert result.plan.gate_in_min == 28
    assert result.plan.gate_out_min == 58
    assert result.rounds[0].responses[2].decision == "COUNTER"
    assert all(c.passed for c in result.final_checks)
    assert Scenario.model_validate_json(result.scenario.model_dump_json()) == scenario


@pytest.mark.parametrize("name", ["Insufficient fuel", "No compatible gate"])
def test_no_feasible_samples(name):
    result = negotiate(bundled_scenarios()[name], SimulatedAgents())
    assert result.status == "No feasible plan"
    assert result.plan is None


def test_one_round_returns_fallback_not_consensus(scenario):
    result = negotiate(scenario, SimulatedAgents(), max_rounds=1)
    assert result.status == "Fallback recommendation"
    assert result.round_count == 1
    assert result.plan.gate_id == "G2"
    assert all(c.passed for c in result.final_checks)


def test_stop_early(scenario):
    s = scenario.model_copy(update={"original_gate": "G2"})
    assert negotiate(s, SimulatedAgents(), max_rounds=3).round_count == 1


@pytest.mark.parametrize("limit", [0, 4, -1])
def test_invalid_round_limit(scenario, limit):
    with pytest.raises(ValueError):
        negotiate(scenario, SimulatedAgents(), max_rounds=limit)


@pytest.mark.parametrize(
    "field",
    [
        "fuel_remaining_kg",
        "remaining_plan_fuel_kg",
        "fuel_buffer_kg",
        "holding_burn_kg_min",
    ],
)
def test_missing_fuel_stops_before_agent(scenario, field):
    class NeverCall(SimulatedAgents):
        def evaluate(self, *args):
            pytest.fail("Must not call an agent with incomplete inputs.")

    result = negotiate(scenario.model_copy(update={field: None}), NeverCall())
    assert result.status == "Missing information"
    assert field in result.missing_fields
    assert result.round_count == 0


def test_boundaries_and_gate_overlap(scenario):
    assert "RUNWAY_OPEN" in fails(
        scenario, make_candidate(scenario, 19, "SIM-RWY1", "G2", 1)
    )
    assert not fails(scenario, make_candidate(scenario, 20, "SIM-RWY1", "G2", 1))
    # 20 minutes of hold leaves exactly the configured requirement + buffer.
    assert "FUEL_BUDGET" not in fails(
        scenario, make_candidate(scenario, 30, "SIM-RWY1", "G2", 1)
    )
    assert "FUEL_BUDGET" in fails(
        scenario, make_candidate(scenario, 31, "SIM-RWY1", "G2", 1)
    )
    s = scenario.model_copy(
        update={"gates": (Gate(id="G1", occupied=(Interval(start=28, end=40),)),)}
    )
    assert "GATE_AVAILABLE" in fails(s, make_candidate(s, 20, "SIM-RWY1", "G1", 1))
    assert "GATE_AVAILABLE" not in fails(s, make_candidate(s, 32, "SIM-RWY1", "G1", 1))


def test_full_occupancy_and_start_separation(scenario):
    s = scenario.model_copy(
        update={
            "runways": (
                Runway(
                    id="R", reservations=(Interval(start=20, end=22),), separation_min=3
                ),
            )
        }
    )
    assert "RUNWAY_OCCUPANCY" in fails(s, make_candidate(s, 21, "R", "G2", 1))
    assert "RUNWAY_SEPARATION" in fails(s, make_candidate(s, 22, "R", "G2", 1))
    assert "RUNWAY_SEPARATION" not in fails(s, make_candidate(s, 23, "R", "G2", 1))
    assert "RUNWAY_OCCUPANCY" not in fails(s, make_candidate(s, 18, "R", "G2", 1))


def test_gate_handling_and_derived_timings(scenario):
    s = scenario.model_copy(
        update={"gates": (Gate(id="G1", handling_available=False),)}
    )
    p = make_candidate(s, 20, "SIM-RWY1", "G1", 1)
    assert "HANDLING_AVAILABLE" in fails(s, p)
    tampered = p.model_copy(
        update={"gate_in_min": 0, "gate_out_min": 1, "state_version": 99}
    )
    assert {"TAXI_TIMING", "TURNAROUND_TIMING", "STATE_VERSION"} <= fails(s, tampered)


class AlwaysAccept(SimulatedAgents):
    def evaluate(self, role, scenario, candidate, checks, history):
        return AgentResponse(
            role=role,
            candidate_id=candidate.id,
            candidate_version=candidate.version,
            state_version=candidate.state_version,
            decision="ACCEPT",
            failed_rule_ids=[],
            explanation="Accept",
        )


def test_llm_acceptance_cannot_override_checks(scenario):
    result = negotiate(scenario, AlwaysAccept())
    assert result.status != "Agreed"
    assert "GATE_AVAILABLE" in fails(scenario, result.rounds[0].candidate)


def test_stale_approval_rejected(scenario):
    class Stale(AlwaysAccept):
        is_live = True

        def evaluate(self, *args):
            return super().evaluate(*args).model_copy(update={"candidate_version": 42})

    result = negotiate(scenario, Stale())
    assert result.status == "Fallback recommendation"
    assert result.api_request_count == 3
    assert result.agent_message_count == 0
    assert len(result.rounds[0].errors) == 3


@pytest.mark.parametrize("error_type", [TimeoutError, PermissionError, ValueError])
def test_provider_failures_fall_back_without_retries(scenario, error_type):
    class Failed(SimulatedAgents):
        is_live = True

        def evaluate(self, *args):
            raise error_type("secret must never be exported")

    result = negotiate(scenario, Failed())
    assert result.status == "Fallback recommendation"
    assert result.round_count == 1
    assert result.api_request_count == 3
    assert "secret must never" not in result.model_dump_json()


def test_unsafe_counterproposal_cannot_bypass_rules(scenario):
    class Unsafe(AlwaysAccept):
        def evaluate(self, *args):
            response = super().evaluate(*args)
            return response.model_copy(
                update={
                    "decision": "COUNTER",
                    "proposed_changes": ProposedChanges(
                        landing_min=0, gate_id="MADE-UP"
                    ),
                }
            )

    result = negotiate(scenario, Unsafe())
    assert result.status == "Fallback recommendation"
    assert result.plan.gate_id == "G2"
    assert result.round_count == 1


def test_needs_information_is_not_acceptance(scenario):
    class Missing(AlwaysAccept):
        def evaluate(self, *args):
            return (
                super()
                .evaluate(*args)
                .model_copy(update={"decision": "NEED_INFORMATION"})
            )

    result = negotiate(scenario, Missing())
    assert result.status == "Missing information"
    assert result.plan is None


def test_repeated_counter_stops(scenario):
    class Repeat(AlwaysAccept):
        def evaluate(self, *args):
            response = super().evaluate(*args)
            return response.model_copy(
                update={"decision": "COUNTER", "proposed_changes": ProposedChanges()}
            )

    result = negotiate(scenario.model_copy(update={"original_gate": "G2"}), Repeat(), 3)
    assert result.round_count == 1
    assert "repeated" in result.reason


def test_input_models_reject_nonfinite_and_invalid_intervals(scenario):
    for update in [
        {"holding_burn_kg_min": 0},
        {"fuel_remaining_kg": float("nan")},
        {"fuel_remaining_kg": float("inf")},
        {"turnaround_min": 0},
    ]:
        with pytest.raises(ValidationError):
            Scenario.model_validate({**scenario.model_dump(), **update})
    with pytest.raises(ValidationError):
        Interval(start=4, end=4)


def test_omitted_fuel_is_missing_not_an_invented_default(scenario):
    data = scenario.model_dump()
    del data["fuel_remaining_kg"]
    result = negotiate(Scenario.model_validate(data), SimulatedAgents())
    assert result.status == "Missing information"
    assert result.round_count == 0


def test_claude_adapter_uses_independent_structured_calls(monkeypatch, scenario):
    import anthropic

    calls = []

    def parse(**kwargs):
        payload = json.loads(kwargs["messages"][0]["content"])
        calls.append(kwargs)
        p = payload["candidate"]
        return SimpleNamespace(
            parsed_output=AgentResponse(
                role=payload["role"],
                candidate_id=p["id"],
                candidate_version=p["version"],
                state_version=p["state_version"],
                decision="ACCEPT",
                failed_rule_ids=[],
                explanation="Role check passed.",
            )
        )

    def client(**kwargs):
        assert kwargs == {"timeout": 25.0, "max_retries": 0}
        return SimpleNamespace(messages=SimpleNamespace(parse=parse))

    monkeypatch.setattr(anthropic, "Anthropic", client)
    result = negotiate(
        scenario.model_copy(update={"original_gate": "G2"}), ClaudeAgents()
    )
    assert result.status == "Agreed"
    assert len(calls) == result.api_request_count == 3
    assert len({call["system"] for call in calls}) == 3
    assert all(call["output_format"] is AgentResponse for call in calls)
