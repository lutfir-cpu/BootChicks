"""The decision log exposes what each agent was given, decided and why, without changing the negotiation."""

from fastapi.testclient import TestClient
from test_frontend_api import submit

import bootchicks.negotiation
from bootchicks.api import create_app
from bootchicks.decisions import decision_log
from bootchicks.providers import StubProvider, prompt_identity, resolve_prompts
from bootchicks.schemas import ROLES, AuditEvent


def decisions(client, state):
    response = client.get(f"/runs/{state['run_id']}/decisions")
    assert response.status_code == 200, response.text
    return response.json()


def test_consensus_log_shows_inputs_proposals_votes_and_selection(tmp_path):
    with TestClient(create_app(tmp_path / "consensus.sqlite")) as client:
        state = submit(client, "c", mode="stub", environment="c")
        log = decisions(client, state)
    assert log["status"] == "CONSENSUS" and log["finished"] is True
    assert log["flight_id"] == "SYNTHETIC-DEMO"
    for number in ("1", "2"):
        agents = log["rounds"][number]["agents"]
        assert {role: a["status"] for role, a in agents.items()} == dict.fromkeys(
            ROLES, "DECIDED"
        )
    first = log["rounds"]["1"]["agents"]
    assert {"label": "Runway R1", "value": "closed 06:00-06:22"} in first["ATC"][
        "given"
    ]
    assert {"label": "Fuel on board", "value": "6,000 kg"} in first["PILOT"]["given"]
    assert {"label": "Assigned gate", "value": "A1"} in first["GROUND"]["given"]
    proposal = first["ATC"]["proposals"][0]
    assert proposal["label"] == "preferred" and proposal["action"]["runway_id"] == "R1"
    assert proposal["rationale"]
    assert first["ATC"]["provider"] == "deterministic-fixture"
    assert first["ATC"]["custom_prompt"] is False

    board = log["board"]["candidates"]
    assert sum(c["feasible"] for c in board) == 3 and len(board) == 4
    vote = log["rounds"]["2"]["agents"]["GROUND"]["votes"][0]
    assert vote["decision"] == "ACCEPT" and vote["action"]["gate_id"]
    assert log["rounds"]["2"]["agents"]["ATC"]["given"][0] == {
        "label": "Feasible plans to vote on",
        "value": "3 of 4",
    }

    decision = log["decision"]
    assert decision["selected_hash"] == state["result"]["selected_plan"]["plan_hash"]
    assert len(decision["unanimous_candidates"]) == 3
    assert set(decision["domain_costs"]) == set(ROLES)
    assert decision["commit"]["reservations"] > 0
    assert decision["commit"]["runway_id"] == "R1"
    assert (
        decision["terminal"]["reason_text"]
        == "Unanimous vote, revalidated and committed."
    )

    timeline = log["timeline"]
    assert [e["sequence"] for e in timeline] == sorted(e["sequence"] for e in timeline)
    assert {e["actor"] for e in timeline} == {*ROLES, "SYSTEM"}
    assert any(
        e["actor"] == "PILOT"
        and e["round"] == 2
        and e["message"].startswith("Voted on 3 plans")
        for e in timeline
    )
    assert timeline[-1]["message"].startswith("Run finished: Consensus.")


def test_runs_without_agents_explain_the_fallback(tmp_path):
    with TestClient(create_app(tmp_path / "fallback.sqlite")) as client:
        state = submit(client, "f", mode="fallback", scenario_id="diversion")
        log = decisions(client, state)
    assert log["status"] == "FALLBACK"
    assert log["rounds"] == {} and log["board"] is None
    assert log["decision"]["fallback_reason"] == (
        "Agents were skipped; the deterministic planner chose directly."
    )
    assert log["decision"]["commit"]["runway_id"] == "R1"
    assert {e["actor"] for e in log["timeline"]} == {"SYSTEM"}


def test_escalation_lists_the_most_common_failures(tmp_path):
    with TestClient(create_app(tmp_path / "escalated.sqlite")) as client:
        state = submit(client, "e", mode="stub", scenario_id="insufficient_fuel")
        log = decisions(client, state)
    assert log["status"] == "ESCALATED"
    assert "2" not in log["rounds"]
    assert (
        log["decision"]["fallback_reason"]
        == "None of the proposed plans passed every hard check."
    )
    rejections = log["decision"]["rejections"]
    assert rejections["plans"] > 0 and rejections["most_common"][0]["plans"] > 0


def test_an_agent_that_fails_is_shown_as_no_reply(tmp_path):
    class SilentPilot(StubProvider):
        async def respond(self, role, round_number, context, response_schema):
            if role == "PILOT" and round_number == 2:
                raise TimeoutError
            return await super().respond(role, round_number, context, response_schema)

    app = create_app(
        tmp_path / "absent.sqlite", provider_factory=lambda _: SilentPilot()
    )
    with TestClient(app) as client:
        state = submit(client, "a", mode="stub", environment="a")
        log = decisions(client, state)
    pilot = log["rounds"]["2"]["agents"]["PILOT"]
    assert pilot["status"] == "NO_REPLY"
    assert pilot["absent_reason"] == "The agent call failed (TimeoutError)."
    assert log["rounds"]["2"]["agents"]["ATC"]["status"] == "DECIDED"
    assert log["decision"]["fallback_reason"] == (
        "An agent did not return a valid round 2 vote in time."
    )


def test_live_logs_flag_only_the_roles_whose_prompt_was_edited(tmp_path, monkeypatch):
    class FakeClaude(StubProvider):
        def __init__(self, system_prompts=None):
            self.system_prompts = resolve_prompts(system_prompts)
            self.prompt_version = prompt_identity(self.system_prompts)

        async def close(self):
            pass

    monkeypatch.setattr(bootchicks.negotiation, "ClaudeProvider", FakeClaude)
    custom = {"GROUND": "Prefer the assigned gate above all else."}
    with TestClient(create_app(tmp_path / "live.sqlite")) as client:
        state = submit(client, "l", mode="live", environment="l", role_prompts=custom)
        log = decisions(client, state)
    agents = log["rounds"]["1"]["agents"]
    assert {role: a["custom_prompt"] for role, a in agents.items()} == {
        "ATC": False,
        "PILOT": False,
        "GROUND": True,
    }


def test_agents_still_deciding_when_a_run_ends_have_no_reply(tmp_path):
    with TestClient(create_app(tmp_path / "partial.sqlite")) as client:
        state = submit(client, "p", mode="stub", environment="p")
        events = client.get(f"/runs/{state['run_id']}/events").json()
    started = [AuditEvent.model_validate(e) for e in events[:3]]
    assert started[-1].kind == "ROUND_INPUT"
    live = decision_log({"run_id": "r", "status": "RUNNING"}, started)
    assert live["finished"] is False
    assert {a["status"] for a in live["rounds"]["1"]["agents"].values()} == {"DECIDING"}
    ended = decision_log({"run_id": "r", "status": "FAILED"}, started)
    assert {a["status"] for a in ended["rounds"]["1"]["agents"].values()} == {
        "NO_REPLY"
    }


def test_unknown_runs_are_not_found(tmp_path):
    with TestClient(create_app(tmp_path / "missing.sqlite")) as client:
        assert client.get("/runs/nope/decisions").status_code == 404


def test_a_reply_that_breaks_a_message_rule_names_the_rule(tmp_path):
    class SloppyPilot(StubProvider):
        async def respond(self, role, round_number, context, response_schema):
            reply = await super().respond(role, round_number, context, response_schema)
            if role == "PILOT" and round_number == 2:
                votes = tuple(
                    v.model_copy(update={"preference_rank": 1}) for v in reply.votes
                )
                return reply.model_copy(update={"votes": votes})
            return reply

    app = create_app(tmp_path / "rule.sqlite", provider_factory=lambda _: SloppyPilot())
    with TestClient(app) as client:
        state = submit(client, "r", mode="stub", environment="r")
        events = client.get(f"/runs/{state['run_id']}/events").json()
        log = decisions(client, state)
    absent = next(e for e in events if e["kind"] == "AGENT_ABSENT")
    assert absent["payload"] == {
        "round": 2,
        "sender": "PILOT",
        "reason": "ProtocolViolation",
        "rule": "INVALID_OR_DUPLICATE_RANKS",
    }
    pilot = log["rounds"]["2"]["agents"]["PILOT"]
    assert pilot["status"] == "NO_REPLY"
    assert pilot["absent_reason"] == "The vote ranks were not 1 to N without repeats."
