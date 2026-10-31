"""Two communication rounds: proposals, then exact conditional votes. No arbitration LLM."""

import asyncio
import os
import time
from dataclasses import dataclass

from .constraints import evaluate, fairness_rank, fallback_rank, improvement
from .providers import PROMPT_VERSION, ClaudeProvider, ReplayProvider, StubProvider
from .scenario import actions, candidate, catalogue, load_snapshot
from .schemas import (
    ROLES,
    ConsensusCertificate,
    Provenance,
    RoundOneResponse,
    RoundTwoResponse,
    RunRequest,
    RunResult,
    digest,
)


class BudgetExpired(TimeoutError):
    pass


def check_budget(deadline):
    if time.monotonic() >= deadline:
        raise BudgetExpired("TOTAL_DEADLINE_EXCEEDED")


def enumerate_feasible(snapshot, deadline, alternate=False):
    result = []
    for action in actions(snapshot, alternate):
        check_budget(deadline)
        report = evaluate(snapshot, candidate(snapshot, action))
        if report.feasible:
            result.append(report)
    return result


def baseline_for(snapshot, deadline):
    choices = []
    for action in actions(snapshot):
        check_budget(deadline)
        if action.gate_id != snapshot.preferred_gate:
            continue
        report = evaluate(snapshot, candidate(snapshot, action))
        if report.feasible:
            choices.append(report)
    approaches = [a.id for a in snapshot.destination.approaches]
    return (
        min(
            choices,
            key=lambda e: (
                e.outcomes.touchdown,
                approaches.index(e.candidate.action.approach_id),
                e.candidate.candidate_id,
            ),
        )
        if choices
        else None
    )


def validate_reply(role, number, response, snapshot, context):
    expected = RoundOneResponse if number == 1 else RoundTwoResponse
    response = expected.model_validate(
        response.model_dump() if hasattr(response, "model_dump") else response
    )
    if (
        response.sender != role
        or response.snapshot_version != snapshot.snapshot_version
    ):
        raise ValueError("WRONG_SENDER_OR_SNAPSHOT")
    if number == 1:
        allowed = {digest(a) for a in actions(snapshot)}
        if any(digest(p.action) not in allowed for p in response.proposals):
            raise ValueError("UNKNOWN_ACTION_OR_RESOURCE")
        if len({p.label for p in response.proposals}) != len(response.proposals):
            raise ValueError("DUPLICATE_PROPOSAL_LABEL")
        if any(
            c.constraint_id not in context["allowed_constraint_ids"]
            for c in response.constraint_references
        ):
            raise ValueError("UNKNOWN_CONSTRAINT_REFERENCE")
    else:
        expected_hashes = {
            e["candidate"]["candidate_id"]: e["candidate"]["plan_hash"]
            for e in context["evaluations"]
        }
        if len(response.votes) != len(expected_hashes) or {
            v.candidate_id for v in response.votes
        } != set(expected_hashes):
            raise ValueError("INCOMPLETE_OR_DUPLICATE_VOTE_SET")
        if {v.preference_rank for v in response.votes} != set(
            range(1, len(response.votes) + 1)
        ):
            raise ValueError("INVALID_OR_DUPLICATE_RANKS")
        message_ids = {m["event_id"] for m in context["proposal_board"]}
        other_ids = {
            m["event_id"]
            for m in context["proposal_board"]
            if m["payload"]["sender"] != role
        }
        for vote in response.votes:
            if expected_hashes.get(vote.candidate_id) != vote.plan_hash:
                raise ValueError("UNKNOWN_PLAN_HASH")
            if (
                not set(vote.proposal_references) <= message_ids
                or not set(vote.proposal_references) & other_ids
            ):
                raise ValueError("INVALID_CROSS_DOMAIN_REFERENCE")
    return response


@dataclass
class RunCounters:
    rounds: int = 0
    responses: int = 0
    requests: int = 0


async def role_round(
    store, run_id, snapshot, provider, number, contexts, request, deadline, counts
):
    check_budget(deadline)
    counts.rounds = number
    counts.requests += 3 if provider.is_live else 0
    schema = RoundOneResponse if number == 1 else RoundTwoResponse

    async def call(role):
        raw = await provider.respond(role, number, contexts[role], schema)
        return validate_reply(role, number, raw, snapshot, contexts[role])

    tasks = {role: asyncio.create_task(call(role)) for role in ROLES}
    remaining = min(request.round_timeout_seconds, deadline - time.monotonic())
    try:
        _, pending = await asyncio.wait(tasks.values(), timeout=max(0, remaining))
    except asyncio.CancelledError:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    replies, events, failed = {}, [], False
    for role in ROLES:  # Stable audit order regardless of network completion order.
        task = tasks[role]
        if task in pending:
            store.append(
                run_id,
                "AGENT_ABSENT",
                {"round": number, "sender": role, "reason": "ROUND_DEADLINE"},
            )
            failed = True
            continue
        try:
            reply = task.result()
        except Exception as exc:  # noqa: BLE001 - provider boundary, never serialize raw exceptions.
            store.append(
                run_id,
                "AGENT_ABSENT",
                {"round": number, "sender": role, "reason": type(exc).__name__},
            )
            failed = True
            continue
        counts.responses += 1
        payload = {
            "schema_version": "1.0",
            "round": number,
            "sender": role,
            "recipients": [r for r in ROLES if r != role],
            "message_type": "PROPOSAL" if number == 1 else "VOTE",
            "snapshot_version": snapshot.snapshot_version,
            "in_reply_to": []
            if number == 1
            else [e["event_id"] for e in contexts[role]["proposal_board"]],
            "mode": request.mode,
            "response_origin": provider.origin,
            "provider": provider.name,
            "model": provider.model,
            "prompt_version": PROMPT_VERSION,
            "response": reply.model_dump(mode="json"),
        }
        event = store.append(run_id, "AGENT_MESSAGE", payload)
        if hasattr(provider, "bind_message_id"):
            provider.bind_message_id(role, number, event.event_id)
        events.append(event.model_dump(mode="json"))
        replies[role] = reply
    return replies, events, failed


def role_contexts(snapshot):
    airport = snapshot.destination
    shared = {
        "flight_id": snapshot.flight_id,
        "clock": snapshot.clock.isoformat(),
        "preferred_gate": snapshot.preferred_gate,
        "destination": airport.iata_code,
        "policy": snapshot.policy.model_dump(mode="json"),
        "operational_provenance": snapshot.operational_provenance,
    }
    domain = {
        "ATC": {
            "runways": [r.model_dump(mode="json") for r in airport.runways],
            "edges": [e.model_dump(mode="json") for e in airport.edges],
            "reservations": [
                r.model_dump(mode="json")
                for r in snapshot.reservations
                if r.resource.startswith(("runway:", "taxi:", "sector:", "arrival:"))
            ],
            "wake_policy": airport.wake_separation_seconds,
            "arrival_limit": airport.rolling_arrival_limit,
            "sector_capacity": airport.sector_capacity,
        },
        "PILOT": {
            "aircraft": snapshot.aircraft.model_dump(mode="json"),
            "connections": [c.model_dump(mode="json") for c in snapshot.connections],
        },
        "GROUND": {
            "gates": [g.model_dump(mode="json") for g in airport.gates],
            "crews": [c.model_dump(mode="json") for c in airport.crews],
            "turnaround_seconds": snapshot.turnaround_seconds,
            "next_departure_target": snapshot.next_departure_target.isoformat(),
            "reservations": [
                r.model_dump(mode="json")
                for r in snapshot.reservations
                if r.resource.startswith(("gate:", "crew:"))
            ],
        },
    }
    sample = next(actions(snapshot))
    allowed = [
        c.constraint_id for c in evaluate(snapshot, candidate(snapshot, sample)).checks
    ]
    return {
        role: {
            "snapshot_version": snapshot.snapshot_version,
            "shared": shared,
            "domain": domain[role],
            "catalogue": catalogue(snapshot),
            "allowed_constraint_ids": allowed,
        }
        for role in ROLES
    }


async def execute(store, run_id, request: RunRequest, provider=None) -> RunResult:
    started = time.monotonic()
    deadline = started + request.total_timeout_seconds
    counts = RunCounters()
    provenance = (
        request.trigger.provenance
        if request.trigger
        else Provenance(source_type="synthetic_fixture")
    )
    store.running(run_id)
    scenario_id = (
        request.trigger.scenario_id if request.trigger else request.scenario_id
    )
    snapshot = store.load_or_seed(load_snapshot(scenario_id, request.trigger))
    baseline = None
    store.append(
        run_id,
        "PREPARED",
        {
            "source_provenance": provenance.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "snapshot_hash": digest(snapshot),
            "policy_hash": digest(snapshot.policy),
            "seed": request.trigger.seed if request.trigger else request.seed,
        },
    )
    accepting_messages = {}

    def result_for(status, reason, selected=None, commit_id=None):
        certificate = None
        if status == "CONSENSUS":
            certificate = ConsensusCertificate(
                plan_hash=selected.candidate.plan_hash,
                snapshot_version=snapshot.snapshot_version,
                policy_version=snapshot.policy.version,
                accepting_messages=accepting_messages,
                validation_report_hash=digest(selected),
                commit_event_id=commit_id,
            )
        return RunResult(
            run_id=run_id,
            status=status,
            terminal_reason=reason,
            mode=request.mode,
            source_provenance=provenance,
            snapshot_version=snapshot.snapshot_version,
            policy_version=snapshot.policy.version,
            rounds_used=counts.rounds,
            logical_agent_responses=counts.responses,
            provider_requests=counts.requests,
            latency_ms=(time.monotonic() - started) * 1000,
            selected_plan=selected.candidate if selected else None,
            evaluation=selected,
            consensus_certificate=certificate,
            fallback_reason=reason if status != "CONSENSUS" else None,
            baseline=baseline,
            improvement_metrics=improvement(baseline, selected),
            audit_event_reference=f"/runs/{run_id}/events",
        )

    async def fallback(reason):
        nonlocal snapshot, baseline
        store.append(run_id, "FALLBACK_STARTED", {"reason": reason})
        try:
            check_budget(deadline)
            snapshot = store.current(snapshot.environment_id)
            baseline = baseline_for(snapshot, deadline)
            options = enumerate_feasible(snapshot, deadline)
            if not options:
                options = enumerate_feasible(snapshot, deadline, alternate=True)
            if not options:
                # Preserve measured rejection evidence without inventing a safe holding/diversion.
                attempts = []
                for action in actions(snapshot):
                    check_budget(deadline)
                    report = evaluate(snapshot, candidate(snapshot, action))
                    attempts.append(
                        {
                            "plan_hash": report.candidate.plan_hash,
                            "failed": [
                                c.model_dump(mode="json")
                                for c in report.checks
                                if not c.passed
                            ],
                        }
                    )
                store.append(
                    run_id,
                    "NO_VALIDATED_PLAN",
                    {"rejections": attempts, "human_review_required": True},
                )
                result = result_for("ESCALATED", "NO_VALIDATED_PLAN")
                store.finish(run_id, result)
                return result
            winner = min(options, key=fallback_rank)
            check_budget(deadline)
            committed = store.commit(
                run_id,
                snapshot,
                winner.candidate,
                lambda report, event_id: result_for(
                    "FALLBACK", reason, report, event_id
                ),
            )
            if committed:
                return committed
            result = result_for("ESCALATED", "FALLBACK_COMMIT_FAILED")
        except BudgetExpired:
            result = result_for("ESCALATED", "TOTAL_DEADLINE_EXCEEDED")
        except Exception as exc:  # noqa: BLE001 - fallback must terminate without a second commit attempt.
            store.append(run_id, "FALLBACK_ERROR", {"error_type": type(exc).__name__})
            result = result_for("ESCALATED", "FALLBACK_ERROR")
        store.finish(run_id, result)
        return result

    owned_provider = False
    try:
        baseline = baseline_for(snapshot, deadline)
        store.append(
            run_id,
            "BASELINE",
            {
                "evaluation": baseline.model_dump(mode="json") if baseline else None,
                "infeasible": baseline is None,
            },
        )
        if request.mode == "fallback":
            return await fallback("DETERMINISTIC_ONLY")
        if provider is None:
            if request.mode == "stub":
                provider = StubProvider()
            elif request.mode == "live":
                provider = ClaudeProvider()
                owned_provider = True
            elif request.mode == "recorded_replay":
                provider = ReplayProvider(os.environ["BOOTCHICKS_REPLAY_FILE"])
        contexts = role_contexts(snapshot)
        # Contexts contain permitted normalized inputs and mock profiles, never historical final outcomes.
        store.append(
            run_id,
            "ROUND_INPUT",
            {"round": 1, "contexts": contexts, "prompt_version": PROMPT_VERSION},
        )
        first, board, failed = await role_round(
            store, run_id, snapshot, provider, 1, contexts, request, deadline, counts
        )
        if failed:
            return await fallback("ROUND_1_FAILURE")
        proposals = {}
        for role in ROLES:
            for proposal in first[role].proposals:
                p = candidate(snapshot, proposal.action)
                proposals.setdefault(
                    p.plan_hash, {"action": proposal.action, "proposers": set()}
                )["proposers"].add(role)
        evaluations = []
        for key in sorted(proposals):
            check_budget(deadline)
            entry = proposals[key]
            evaluations.append(
                evaluate(
                    snapshot, candidate(snapshot, entry["action"], entry["proposers"])
                )
            )
        store.append(
            run_id,
            "PROPOSAL_BOARD",
            {
                "messages": board,
                "evaluations": [e.model_dump(mode="json") for e in evaluations],
            },
        )
        feasible = [e for e in evaluations if e.feasible]
        if not feasible:
            return await fallback("NO_FEASIBLE_PROPOSALS")
        summaries = {role: contexts[role]["domain"] for role in ROLES}
        second_contexts = {
            role: {
                **contexts[role],
                "proposal_board": board,
                "cross_domain_constraints": summaries,
                "evaluations": [e.model_dump(mode="json") for e in feasible],
            }
            for role in ROLES
        }
        store.append(
            run_id,
            "ROUND_INPUT",
            {"round": 2, "contexts": second_contexts, "prompt_version": PROMPT_VERSION},
        )
        second, vote_events, failed = await role_round(
            store,
            run_id,
            snapshot,
            provider,
            2,
            second_contexts,
            request,
            deadline,
            counts,
        )
        if failed:
            return await fallback("ROUND_2_FAILURE")
        common = {e.candidate.candidate_id for e in feasible}
        for role in ROLES:
            common &= {
                v.candidate_id for v in second[role].votes if v.decision == "ACCEPT"
            }
        if not common:
            store.append(
                run_id,
                "NO_UNANIMOUS_PLAN",
                {"votes": {r: second[r].model_dump(mode="json") for r in ROLES}},
            )
            return await fallback("NO_UNANIMOUS_PLAN")
        winner = min(
            (e for e in feasible if e.candidate.candidate_id in common),
            key=fairness_rank,
        )
        accepting_messages.update(
            {e["payload"]["sender"]: e["event_id"] for e in vote_events}
        )
        store.append(
            run_id,
            "SELECTION",
            {
                "unanimous_candidates": sorted(common),
                "selected_hash": winner.candidate.plan_hash,
                "domain_costs": winner.domain_costs,
                "policy": snapshot.policy.model_dump(mode="json"),
            },
        )
        check_budget(deadline)
        committed = store.commit(
            run_id,
            snapshot,
            winner.candidate,
            lambda report, event_id: result_for(
                "CONSENSUS", "UNANIMOUS_VALIDATED_COMMIT", report, event_id
            ),
        )
        return (
            committed
            if committed
            else await fallback("STALE_SNAPSHOT_OR_COMMIT_REVALIDATION_FAILED")
        )
    except BudgetExpired:
        return await fallback("TOTAL_DEADLINE_EXCEEDED")
    except asyncio.CancelledError:
        store.fail(run_id, "RUN_CANCELLED")
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed at external provider boundary.
        store.append(
            run_id, "PROVIDER_OR_PROTOCOL_ERROR", {"error_type": type(exc).__name__}
        )
        return await fallback("PROVIDER_OR_PROTOCOL_ERROR")
    finally:
        if owned_provider:
            await provider.close()
