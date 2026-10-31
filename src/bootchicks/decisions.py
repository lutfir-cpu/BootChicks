"""Readable decision log for one run, rebuilt from its audit events alone.

Nothing here changes how a run negotiates: it reads the recorded trail and states, per agent and per round,
what each role was given, what it decided and why, then what Python decided after it.
It works on a run in progress too, so clients can follow agents as they decide.
"""

from collections import Counter
from datetime import datetime

from .providers import DEFAULT_PROMPTS

ROLES = ("ATC", "PILOT", "GROUND")
ROLE_NAMES = {"ATC": "ATC", "PILOT": "Pilot", "GROUND": "Ground"}
TERMINAL = {"CONSENSUS", "FALLBACK", "ESCALATED", "FAILED"}
OUTCOMES = {
    "CONSENSUS": "Consensus",
    "FALLBACK": "Fallback plan",
    "ESCALATED": "Escalated",
    "FAILED": "Run failed",
}

REASONS = {
    "UNANIMOUS_VALIDATED_COMMIT": "Unanimous vote, revalidated and committed.",
    "DETERMINISTIC_ONLY": "Agents were skipped; the deterministic planner chose directly.",
    "ROUND_1_FAILURE": "An agent did not return a valid round 1 proposal in time.",
    "ROUND_2_FAILURE": "An agent did not return a valid round 2 vote in time.",
    "ROUND_DEADLINE": "The agent did not answer before the round deadline.",
    "NO_FEASIBLE_PROPOSALS": "None of the proposed plans passed every hard check.",
    "NO_UNANIMOUS_PLAN": "No feasible plan was accepted by all three roles.",
    "NO_VALIDATED_PLAN": "Neither the destination nor the alternate has a plan that passes every hard check.",
    "TOTAL_DEADLINE_EXCEEDED": "The run used up its total time budget.",
    "PROVIDER_OR_PROTOCOL_ERROR": "An agent call failed or broke the message protocol.",
    "STALE_SNAPSHOT_OR_COMMIT_REVALIDATION_FAILED": "Airport state changed before commit, so the agreed plan was"
    " revalidated and dropped.",
    "FALLBACK_COMMIT_FAILED": "The fallback plan could not be committed.",
    "FALLBACK_ERROR": "The fallback planner hit an error.",
    "WORKER_STOPPED": "The server stopped while this run was in progress.",
    "RUN_CANCELLED": "The run was cancelled.",
    # Message rules a rejected agent reply broke.
    "WRONG_SENDER_OR_SNAPSHOT": "The reply named the wrong sender or snapshot.",
    "UNKNOWN_ACTION_OR_RESOURCE": "A proposal used an action or resource outside the catalogue.",
    "DUPLICATE_PROPOSAL_LABEL": "Two proposals used the same label.",
    "UNKNOWN_CONSTRAINT_REFERENCE": "The reply cited a constraint that does not exist.",
    "INCOMPLETE_OR_DUPLICATE_VOTE_SET": "The reply did not vote exactly once on every feasible plan.",
    "INVALID_OR_DUPLICATE_RANKS": "The vote ranks were not 1 to N without repeats.",
    "UNKNOWN_PLAN_HASH": "A vote named a plan that is not on the board.",
    "INVALID_CROSS_DOMAIN_REFERENCE": "A vote did not cite another role's proposal.",
    "NO_STRUCTURED_RESPONSE": "The model did not return the required structured reply.",
}


def reason_text(code):
    """Plain words for a terminal, fallback or absence code; unknown codes (such as exception names) read as-is."""
    if not code:
        return None
    return REASONS.get(code, code.replace("_", " ").lower().capitalize() + ".")


def hhmm(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M")


def kg(value):
    return f"{value:,.0f} kg"


def windows(items):
    return ", ".join(f"{hhmm(w['start'])}-{hhmm(w['end'])}" for w in items)


def joined(roles):
    return " and ".join(ROLE_NAMES[r] for r in roles)


def plan_text(action):
    return f"{hhmm(action['landing_slot'])} {action['runway_id'] or action['airport']} gate {action['gate_id']}"


def given(context):
    """The constraints one role sees in round 1, as label and value pairs."""
    shared, domain = context["shared"], context["domain"]
    if "runways" in domain:
        items = [
            (
                f"Runway {r['id']}",
                f"closed {windows(r['closed'])}" if r["closed"] else "open",
            )
            for r in domain["runways"]
        ]
        separations = [
            s for row in domain["wake_policy"].values() for s in row.values()
        ]
        items += [
            ("Wake separation", f"{min(separations)}-{max(separations)} s"),
            ("Rolling arrival limit", str(domain["arrival_limit"])),
            ("Sector capacity", str(domain["sector_capacity"])),
            ("Booked runway and taxi slots", str(len(domain["reservations"]))),
        ]
    elif "aircraft" in domain:
        a = domain["aircraft"]
        items = [
            ("Aircraft", f"{a['type_label']}, wake class {a['wake_class']}"),
            ("Fuel on board", kg(a["fuel_kg"])),
            ("Protected landing fuel", kg(a["protected_landing_kg"])),
            ("Protected on-block fuel", kg(a["protected_on_block_kg"])),
            ("Holding burn", f"{a['hold_burn_kg_min']:,.0f} kg/min"),
        ]
        items += [
            (
                "Connection",
                f"{c['passengers']} passengers, boarding closes {hhmm(c['boarding_deadline'])}",
            )
            for c in domain["connections"]
        ]
    else:
        items = [
            (f"Gate {g['id']}", f"free {windows(g['available'])}")
            for g in domain["gates"]
        ]
        items += [
            (f"Crew {c['id']}", f"shift ends {hhmm(c['shift_end'])}")
            for c in domain["crews"]
        ]
        items += [
            ("Turnaround", f"{domain['turnaround_seconds'] // 60} min"),
            ("Next departure target", hhmm(domain["next_departure_target"])),
            ("Booked gate and crew periods", str(len(domain["reservations"]))),
        ]
    items.append(("Assigned gate", shared["preferred_gate"]))
    return [{"label": label, "value": value} for label, value in items]


def decision_log(state, events):
    """Rebuild the run's decisions from `Store.run` state and its ordered `Store.events`."""
    finished = state["status"] in TERMINAL
    runways = {}
    log = {
        "run_id": state["run_id"],
        "status": state["status"],
        "finished": finished,
        "flight_id": None,
        "clock": None,
        "rounds": {},
        "board": None,
        "decision": {
            "baseline_feasible": None,
            "unanimous_candidates": None,
            "selected_hash": None,
            "domain_costs": None,
            "fairness_policy": None,
            "no_unanimous_plan": False,
            "fallback_reason": None,
            "rejections": None,
            "commit": None,
            "terminal": None,
        },
        "timeline": [],
    }
    rounds, decision = log["rounds"], log["decision"]

    def action(value):
        return {
            **value,
            "runway_id": runways.get((value["airport"], value["taxi_path_id"])),
        }

    def note(event, actor, message, round=None):
        log["timeline"].append(
            {
                "sequence": event.sequence,
                "at": event.timestamp.isoformat(),
                "actor": actor,
                "round": round,
                "kind": event.kind,
                "message": message,
            }
        )

    for event in events:
        p = event.payload
        kind = event.kind
        if kind == "PREPARED":
            snapshot = p["snapshot"]
            log["flight_id"], log["clock"] = snapshot["flight_id"], snapshot["clock"]
            for airport in [snapshot["destination"], *snapshot["alternates"]]:
                for path in airport["paths"]:
                    runways[(airport["iata_code"], path["id"])] = path["runway_id"]
            note(
                event,
                "SYSTEM",
                f"Snapshot prepared for {snapshot['flight_id']} at {hhmm(snapshot['clock'])}",
            )
        elif kind == "BASELINE":
            decision["baseline_feasible"] = not p["infeasible"]
            note(
                event,
                "SYSTEM",
                "No baseline plan passes every hard check"
                if p["infeasible"]
                else "Baseline plan computed without negotiation",
            )
        elif kind == "ROUND_INPUT":
            number = p["round"]
            agents = {}
            for role in ROLES:
                context = p["contexts"][role]
                if number == 1:
                    inputs = given(context)
                else:
                    feasible = len(context["evaluations"])
                    total = (
                        len(log["board"]["candidates"]) if log["board"] else feasible
                    )
                    inputs = [
                        {
                            "label": "Feasible plans to vote on",
                            "value": f"{feasible} of {total}",
                        },
                        {
                            "label": "Proposals from",
                            "value": joined([r for r in ROLES if r != role]),
                        },
                    ]
                agents[role] = {
                    "status": "DECIDING",
                    "received_at": event.timestamp.isoformat(),
                    "decided_at": None,
                    "given": inputs,
                    # Only live runs record prompts; flag the roles whose prompt a user edited.
                    "custom_prompt": p.get("system_prompts", {}).get(
                        role, DEFAULT_PROMPTS[role]
                    )
                    != DEFAULT_PROMPTS[role],
                    "provider": None,
                    "model": None,
                    "prompt_version": p["prompt_version"],
                    "proposals": [],
                    "votes": [],
                    "absent_reason": None,
                }
                if number == 1:
                    note(
                        event,
                        role,
                        "Received the scenario snapshot and its domain constraints",
                        number,
                    )
                else:
                    note(
                        event,
                        role,
                        f"Received the proposal board: {inputs[0]['value']} plans are feasible",
                        number,
                    )
            rounds[str(number)] = {
                "started_at": event.timestamp.isoformat(),
                "agents": agents,
            }
        elif kind == "AGENT_MESSAGE":
            number, role = p["round"], p["sender"]
            agent = rounds[str(number)]["agents"][role]
            response = p["response"]
            agent.update(
                status="DECIDED",
                decided_at=event.timestamp.isoformat(),
                provider=p["provider"],
                model=p["model"],
                prompt_version=p["prompt_version"],
            )
            to = joined(p["recipients"])
            if number == 1:
                agent["proposals"] = [
                    {
                        "label": item["label"],
                        "action": action(item["action"]),
                        "rationale": item["rationale"],
                        "requested_concessions": item["requested_concessions"],
                    }
                    for item in response["proposals"]
                ]
                count = len(agent["proposals"])
                note(
                    event,
                    role,
                    f"Sent {count} complete {'plan' if count == 1 else 'plans'} to {to}",
                    number,
                )
                for item in agent["proposals"]:
                    a = item["action"]
                    note(
                        event,
                        role,
                        f"{item['label'].capitalize()}: {plan_text(a)}. {item['rationale']}",
                        number,
                    )
            else:
                candidates = {
                    c["plan_hash"]: c
                    for c in (log["board"] or {}).get("candidates", [])
                }
                agent["votes"] = [
                    {
                        "candidate_id": vote["candidate_id"],
                        "plan_hash": vote["plan_hash"],
                        "action": candidates[vote["plan_hash"]]["action"]
                        if vote["plan_hash"] in candidates
                        else None,
                        "decision": vote["decision"],
                        "preference_rank": vote["preference_rank"],
                        "reason_codes": vote["reason_codes"],
                        "rationale": vote["rationale"],
                        "accepted_concessions": vote["accepted_concessions"],
                    }
                    for vote in response["votes"]
                ]
                accepted = sum(v["decision"] == "ACCEPT" for v in agent["votes"])
                note(
                    event,
                    role,
                    f"Voted on {len(agent['votes'])} plans: {accepted} accept, {len(agent['votes']) - accepted} reject",
                    number,
                )
                for vote in sorted(agent["votes"], key=lambda v: v["preference_rank"]):
                    verdict = "Accept" if vote["decision"] == "ACCEPT" else "Reject"
                    note(
                        event,
                        role,
                        f"{verdict} {plan_text(vote['action']) if vote['action'] else vote['candidate_id'][:8]}"
                        f" (rank {vote['preference_rank']}). {vote['rationale']}",
                        number,
                    )
        elif kind == "AGENT_ABSENT":
            number, role = p["round"], p["sender"]
            agent = rounds[str(number)]["agents"][role]
            # A broken message rule, a deadline, or the name of the exception the agent call raised.
            code = p.get("rule", p["reason"])
            reason = (
                reason_text(code)
                if code in REASONS
                else f"The agent call failed ({code})."
            )
            agent.update(status="NO_REPLY", absent_reason=reason)
            note(event, role, f"No reply. {reason}", number)
        elif kind == "PROPOSAL_BOARD":
            candidates = [
                {
                    "candidate_id": e["candidate"]["candidate_id"],
                    "plan_hash": e["candidate"]["plan_hash"],
                    "action": action(e["candidate"]["action"]),
                    "proposers": e["candidate"]["proposers"],
                    "feasible": e["feasible"],
                    "checks": [
                        {k: c[k] for k in ("constraint_id", "domain", "passed")}
                        for c in e["checks"]
                    ],
                }
                for e in p["evaluations"]
            ]
            log["board"] = {"at": event.timestamp.isoformat(), "candidates": candidates}
            feasible = sum(c["feasible"] for c in candidates)
            note(
                event,
                "SYSTEM",
                f"Checked {len(candidates)} distinct proposals: {feasible} feasible",
            )
        elif kind == "NO_UNANIMOUS_PLAN":
            decision["no_unanimous_plan"] = True
            note(event, "SYSTEM", "No feasible plan was accepted by all three roles")
        elif kind == "SELECTION":
            decision.update(
                unanimous_candidates=p["unanimous_candidates"],
                selected_hash=p["selected_hash"],
                domain_costs=p["domain_costs"],
                fairness_policy=p["policy"]["version"],
            )
            count = len(p["unanimous_candidates"])
            chosen = next(
                (
                    c
                    for c in (log["board"] or {}).get("candidates", [])
                    if c["plan_hash"] == p["selected_hash"]
                ),
                None,
            )
            note(
                event,
                "SYSTEM",
                f"{count} unanimous {'plan' if count == 1 else 'plans'}; the fairness rule selected"
                f" {plan_text(chosen['action']) if chosen else p['selected_hash'][:8]}",
            )
        elif kind == "FALLBACK_STARTED":
            decision["fallback_reason"] = reason_text(p["reason"])
            note(
                event,
                "SYSTEM",
                f"Deterministic fallback started. {reason_text(p['reason'])}",
            )
        elif kind == "NO_VALIDATED_PLAN":
            failures = Counter(
                c["constraint_id"] for r in p["rejections"] for c in r["failed"]
            )
            decision["rejections"] = {
                "plans": len(p["rejections"]),
                "most_common": [
                    {"constraint_id": cid, "plans": n}
                    for cid, n in failures.most_common(6)
                ],
            }
            note(
                event,
                "SYSTEM",
                f"Fallback tried {len(p['rejections'])} plans; none passed every check",
            )
        elif kind == "RESOURCE_COMMIT":
            runway = next(
                (
                    r["resource"].split(":")[2]
                    for r in p["reservations"]
                    if r["resource"].startswith("runway:")
                ),
                None,
            )
            decision["commit"] = {
                "plan_hash": p["plan_hash"],
                "runway_id": runway,
                "snapshot_before": p["snapshot_before"],
                "snapshot_after": p["snapshot_after"],
                "reservations": len(p["reservations"]),
            }
            note(
                event,
                "SYSTEM",
                f"Revalidated and committed {len(p['reservations'])} resource reservations",
            )
        elif kind == "TERMINAL":
            decision["terminal"] = {
                "status": p["status"],
                "reason": p["reason"],
                "reason_text": reason_text(p["reason"]),
            }
            note(
                event,
                "SYSTEM",
                f"Run finished: {OUTCOMES.get(p['status'], p['status'])}. {reason_text(p['reason'])}",
            )
        elif kind in ("PROVIDER_OR_PROTOCOL_ERROR", "FALLBACK_ERROR"):
            note(event, "SYSTEM", f"{reason_text(kind)} ({p['error_type']})")

    if finished:
        # An agent still deciding when the run ended never replied.
        for entry in rounds.values():
            for agent in entry["agents"].values():
                if agent["status"] == "DECIDING":
                    agent.update(
                        status="NO_REPLY",
                        absent_reason="The run ended before this agent replied.",
                    )
    return log
