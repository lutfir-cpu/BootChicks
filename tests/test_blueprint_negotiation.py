import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bootchicks.negotiation import execute
from bootchicks.providers import ClaudeProvider, ReplayProvider, StubProvider
from bootchicks.schemas import RunRequest, WorkflowInput, digest
from bootchicks.store import IdempotencyConflict, Store


async def replay(tmp_path, request=None, provider=None):
    store = Store(tmp_path / "runs.sqlite")
    request = request or RunRequest()
    run_id, _ = store.open_run(str(uuid4()), request)
    result = await execute(store, run_id, request, provider)
    return result, store


async def test_two_rounds_exact_certificate_and_baseline(tmp_path):
    result, store = await replay(tmp_path)
    assert result.status == "CONSENSUS"
    assert (
        result.rounds_used == 2
        and result.logical_agent_responses == 6
        and result.provider_requests == 0
    )
    cert = result.consensus_certificate
    assert set(cert.accepting_messages) == {"ATC", "PILOT", "GROUND"}
    assert cert.plan_hash == result.selected_plan.plan_hash
    assert cert.validation_report_hash == digest(result.evaluation)
    assert result.improvement_metrics["holding_saved_min"] == 10
    assert result.improvement_metrics["airborne_fuel_saved_kg"] == 400
    assert result.improvement_metrics["overtime_saved_min"] == 8
    events = store.events(result.run_id)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    commit = next(e for e in events if e.kind == "RESOURCE_COMMIT")
    assert commit.event_id == cert.commit_event_id
    assert events[-1].kind == "TERMINAL"
    board = next(e for e in events if e.kind == "PROPOSAL_BOARD")
    assert len(board.payload["evaluations"]) <= 9
    assert len(board.payload["messages"]) == 3
    second = next(
        e for e in events if e.kind == "ROUND_INPUT" and e.payload["round"] == 2
    )
    for context in second.payload["contexts"].values():
        assert len(context["proposal_board"]) == 3
        assert set(context["cross_domain_constraints"]) == {"ATC", "PILOT", "GROUND"}
        assert all(e["feasible"] for e in context["evaluations"])


async def test_real_trigger_never_sends_historical_outcomes_to_agents(tmp_path):
    path = Path(__file__).resolve().parents[1] / "data/fixtures/real_trigger.json"
    trigger = WorkflowInput.model_validate_json(path.read_bytes())
    result, store = await replay(tmp_path, RunRequest(trigger=trigger))
    assert result.status == "CONSENSUS"
    for event in store.events(result.run_id):
        if event.kind == "ROUND_INPUT":
            text = json.dumps(event.payload)
            assert (
                "WHEELS_ON" not in text
                and "ARRIVAL_DELAY" not in text
                and "ARRIVAL_TIME" not in text
            )
    assert result.source_provenance.raw_flight["WHEELS_ON"]


@pytest.mark.parametrize(
    "scenario,status,action",
    [
        ("insufficient_fuel", "ESCALATED", None),
        ("no_gate", "ESCALATED", None),
        ("diversion", "FALLBACK", "DIVERT"),
    ],
)
async def test_terminal_paths(tmp_path, scenario, status, action):
    result, store = await replay(tmp_path, RunRequest(scenario_id=scenario))
    assert result.status == status
    assert result.consensus_certificate is None
    if action:
        assert (
            result.selected_plan.action.action == action
            and result.selected_plan.action.airport == "DAL"
        )
    else:
        assert result.selected_plan is None
        assert any(e.kind == "NO_VALIDATED_PLAN" for e in store.events(result.run_id))


async def test_no_key_deterministic_fallback(tmp_path):
    result, _ = await replay(tmp_path, RunRequest(mode="fallback"))
    assert result.status == "FALLBACK"
    assert (
        result.rounds_used
        == result.logical_agent_responses
        == result.provider_requests
        == 0
    )
    assert result.consensus_certificate is None


def test_cli_fallback_commit_exception_stops_without_retry(tmp_path, monkeypatch):
    from bootchicks.cli import main

    attempts = []

    def failed_commit(self, *args):
        attempts.append(args)
        raise ValueError("simulated commit failure")

    output = tmp_path / "result.json"
    monkeypatch.setattr(Store, "commit", failed_commit)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bootchicks",
            "run",
            "--mode",
            "fallback",
            "--database",
            str(tmp_path / "cli.sqlite"),
            "--output",
            str(output),
        ],
    )
    main()
    result = json.loads(output.read_text())
    assert len(attempts) == 1
    assert result["status"] == "ESCALATED"
    assert result["result"]["terminal_reason"] == "FALLBACK_ERROR"
    assert result["result"]["selected_plan"] is None


async def test_timeout_cancels_all_roles_and_falls_back(tmp_path):
    class Slow(StubProvider):
        is_live = True
        cancelled = set()

        async def respond(self, role, *args):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled.add(role)
                raise

    provider = Slow()
    result, store = await replay(
        tmp_path,
        RunRequest(round_timeout_seconds=0.01, total_timeout_seconds=2),
        provider,
    )
    assert result.status == "FALLBACK"
    assert (
        result.rounds_used == 1
        and result.logical_agent_responses == 0
        and result.provider_requests == 3
    )
    assert provider.cancelled == {"ATC", "PILOT", "GROUND"}
    assert (
        len([e for e in store.events(result.run_id) if e.kind == "AGENT_ABSENT"]) == 3
    )


async def test_total_deadline_includes_preparation(tmp_path):
    result, _ = await replay(tmp_path, RunRequest(total_timeout_seconds=0.000001))
    assert result.status == "ESCALATED"
    assert result.terminal_reason == "TOTAL_DEADLINE_EXCEEDED"
    assert result.rounds_used == 0


@pytest.mark.parametrize(
    "failure", ["malformed", "rate_limit", "wrong_sender", "unknown_action"]
)
async def test_invalid_first_response_fails_closed(tmp_path, failure):
    class Bad(StubProvider):
        async def respond(self, role, number, context, schema):
            if role == "ATC":
                if failure == "rate_limit":
                    raise RuntimeError("secret credentials must not be logged")
                if failure == "malformed":
                    return {"unexpected": "not a response"}
            reply = await super().respond(role, number, context, schema)
            if role == "ATC":
                if failure == "wrong_sender":
                    return reply.model_copy(update={"sender": "PILOT"})
                proposal = reply.proposals[0]
                return reply.model_copy(
                    update={
                        "proposals": (
                            proposal.model_copy(
                                update={
                                    "action": proposal.action.model_copy(
                                        update={"gate_id": "INVENTED"}
                                    )
                                }
                            ),
                        )
                    }
                )
            return reply

    result, store = await replay(tmp_path, provider=Bad())
    assert result.status == "FALLBACK"
    assert result.fallback_reason == "ROUND_1_FAILURE"
    assert result.rounds_used == 1
    assert "secret credentials" not in json.dumps(
        [e.model_dump(mode="json") for e in store.events(result.run_id)]
    )


@pytest.mark.parametrize(
    "failure",
    ["missing_vote", "duplicate_rank", "wrong_hash", "wrong_reference", "reject_all"],
)
async def test_vote_validation_and_no_unanimity(tmp_path, failure):
    class BadVotes(StubProvider):
        async def respond(self, role, number, context, schema):
            response = await super().respond(role, number, context, schema)
            if number != 2 or role != "PILOT":
                return response
            votes = list(response.votes)
            if failure == "missing_vote":
                votes = votes[:-1]
            elif failure == "duplicate_rank":
                votes = [v.model_copy(update={"preference_rank": 1}) for v in votes]
            elif failure == "wrong_hash":
                votes[0] = votes[0].model_copy(update={"plan_hash": "unknown"})
            elif failure == "wrong_reference":
                votes[0] = votes[0].model_copy(
                    update={"proposal_references": ("made-up",)}
                )
            elif failure == "reject_all":
                votes = [v.model_copy(update={"decision": "REJECT"}) for v in votes]
            return response.model_copy(update={"votes": tuple(votes)})

    result, _ = await replay(tmp_path, provider=BadVotes())
    assert result.status == "FALLBACK" and result.consensus_certificate is None
    assert result.rounds_used == 2
    assert result.fallback_reason == (
        "NO_UNANIMOUS_PLAN" if failure == "reject_all" else "ROUND_2_FAILURE"
    )


async def test_completion_order_does_not_change_selection(tmp_path):
    class Reordered(StubProvider):
        async def respond(self, role, *args):
            await asyncio.sleep({"ATC": 0.015, "PILOT": 0.005, "GROUND": 0}[role])
            return await super().respond(role, *args)

    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    a, _ = await replay(tmp_path / "first")
    b, _ = await replay(tmp_path / "second", provider=Reordered())
    assert a.selected_plan.plan_hash == b.selected_plan.plan_hash


async def test_concurrent_runs_cannot_double_book_same_flight(tmp_path):
    store = Store(tmp_path / "shared.sqlite")
    request = RunRequest()
    first, _ = store.open_run("first", request)
    second, _ = store.open_run("second", request)
    results = await asyncio.gather(
        execute(store, first, request), execute(store, second, request)
    )
    assert sorted(r.status for r in results) == ["CONSENSUS", "ESCALATED"]
    winner = next(r for r in results if r.status == "CONSENSUS")
    snapshot = store.current(winner.selected_plan.snapshot_version.rsplit(":v", 1)[0])
    target_bookings = [
        r for r in snapshot.reservations if r.flight_id == snapshot.flight_id
    ]
    assert len(target_bookings) == len(winner.evaluation.reservations)


async def test_stale_votes_fallback_uses_fresh_snapshot(tmp_path):
    store = Store(tmp_path / "stale.sqlite")
    request = RunRequest()
    run_id, _ = store.open_run("stale", request)

    class StateChange(StubProvider):
        async def respond(self, role, number, context, schema):
            if number == 2 and role == "ATC":
                environment = context["snapshot_version"].rsplit(":v", 1)[0]
                current = store.current(environment)
                from bootchicks.schemas import Window

                airport = current.destination.model_copy(
                    update={
                        "runways": tuple(
                            r.model_copy(
                                update={
                                    "closed": (
                                        Window(
                                            start=current.clock, end=current.valid_until
                                        ),
                                    )
                                }
                            )
                            for r in current.destination.runways
                        )
                    }
                )
                changed = current.model_copy(
                    update={"version": current.version + 1, "destination": airport}
                )
                with store.connect() as db:
                    db.execute(
                        "UPDATE snapshots SET snapshot_json=? WHERE environment_id=?",
                        (changed.model_dump_json(), environment),
                    )
            return await super().respond(role, number, context, schema)

    result = await execute(store, run_id, request, StateChange())
    assert result.status == "FALLBACK"
    assert result.selected_plan.action.action == "DIVERT"
    assert result.snapshot_version.endswith(":v2")
    assert result.rounds_used == 2 and result.logical_agent_responses == 6
    assert result.consensus_certificate is None


async def test_recorded_replay_is_labelled_and_hashes_stay_exact(tmp_path):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    original, store = await replay(tmp_path / "first")
    path = tmp_path / "events.jsonl"
    path.write_text(
        "".join(e.model_dump_json() + "\n" for e in store.events(original.run_id))
    )
    replayed, again = await replay(
        tmp_path / "second", RunRequest(mode="recorded_replay"), ReplayProvider(path)
    )
    assert replayed.status == "CONSENSUS"
    assert replayed.selected_plan.plan_hash == original.selected_plan.plan_hash
    assert replayed.mode == "recorded_replay" and replayed.provider_requests == 0
    assert all(
        e.payload["response_origin"] == "recorded_replay"
        for e in again.events(replayed.run_id)
        if e.kind == "AGENT_MESSAGE"
    )


async def test_claude_adapter_makes_six_separate_typed_requests(tmp_path, monkeypatch):
    import anthropic

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 120, "max_retries": 0}
            self.messages = SimpleNamespace(parse=self.parse)

        async def parse(self, **kwargs):
            calls.append(kwargs)
            payload = json.loads(kwargs["messages"][0]["content"])
            role = next(
                r
                for r in ["ATC", "PILOT", "GROUND"]
                if f"independent {r} domain" in kwargs["system"]
            )
            response = await StubProvider().respond(
                role, payload.pop("round"), payload, kwargs["output_format"]
            )
            return SimpleNamespace(parsed_output=response)

        async def close(self):
            pass

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    result, _ = await replay(tmp_path, RunRequest(mode="live"), ClaudeProvider())
    assert result.status == "CONSENSUS" and result.provider_requests == 6
    assert len(calls) == 6
    assert len({c["system"] for c in calls}) == 3


def test_idempotency_and_restart_recovery(tmp_path):
    store = Store(tmp_path / "persistent.sqlite")
    request = RunRequest()
    run_id, created = store.open_run("same", request)
    assert created and store.open_run("same", request) == (run_id, False)
    with pytest.raises(IdempotencyConflict):
        store.open_run("same", RunRequest(mode="fallback"))
    store.running(run_id)
    restarted = Store(tmp_path / "persistent.sqlite")
    assert restarted.recover_interrupted() == [run_id]
    assert restarted.run(run_id)["status"] == "FAILED"
    assert restarted.open_run("same", request) == (run_id, False)


def test_single_runtime_ownership(tmp_path):
    store = Store(tmp_path / "owner.sqlite")
    with store.process_lock():
        with pytest.raises(RuntimeError, match="running worker"):
            with Store(tmp_path / "owner.sqlite").process_lock():
                pass
