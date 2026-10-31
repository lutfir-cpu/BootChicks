# BootChicks - Demo and Judging Guide

Companion to `BootChicks_Blueprint.md` · 31 October 2026.

## 1. Purpose and relationship to the build

The original blueprint remains the implementation specification.
This guide describes how to demonstrate, evaluate and explain the MVP against the supplied judging rubric.
It does not restart development, change the negotiation protocol or introduce a second architecture.

Use existing outputs wherever possible.
Add small evidence/export fields only when the current build cannot expose a claim needed for judging.
Do not delay a working end-to-end submission for presentation infrastructure.

The demo flow below is a sequence of information to show.
It can be delivered through the existing app, API responses, terminal output or a prepared evidence report.
It does not prescribe a UI layout.

## 2. The story judges should understand

**Proposed primary user:** an airport operations duty manager reviewing a recovery recommendation for one disrupted arrival.
ATC, pilot and ground operations remain separate decision-making domains; the duty manager does not acquire authority to issue all their operational instructions.

**Narrow task:** find an arrival slot, usable taxi route, compatible gate and available crew after a runway disruption, while preserving configured separation and fuel margins.

**Current process, based on the challenge description:** different organisations coordinate through calls and manual software updates.
Changes in one domain can invalidate another domain's plan and require another coordination cycle.

**What the MVP demonstrates:** independent agents exchange structured priorities and proposals, code rejects invalid options, and all three agents explicitly accept an exact plan within two communication rounds - or the system visibly falls back or escalates.

This is an operational simulation.
Real historical flight inputs anchor the scenario; the fuel, weather, runway, gate and crew state is synthetic and labelled.
Do not describe the prototype as certified, operationally deployed or validated against real airport decisions.

## 3. What each rubric item needs as evidence

| Criterion | Weight | Evidence to show | Claim to avoid |
| --- | --- | --- | --- |
| Problem realism | 20% | Specific user, one disrupted flight, cross-domain conflict and current coordination process | A generic assistant for all aviation |
| Technical soundness | 25% | Three independent agent calls, structured proposals, deterministic checks, exact approvals and working output | LLM-generated arithmetic or a scripted successful vote |
| Honest evaluation | 20% | Named test cases, denominators, actual results and a visible failure | A single success presented as general reliability |
| Trust and traceability | 20% | Source/fixture labels, applied rules, numerical margins, agent acceptances and review status | Mock parameters presented as authoritative aviation limits |
| Impact | 10% | Same-scenario baseline/result comparison with clearly labelled modeled outcomes | Real-world savings inferred from an invented manual baseline |
| Time discipline | 5% | Valid submission, rehearsed three-minute presentation, labelled backup replay | A rushed feature expansion that prevents a working demo |

## 4. Demo sequence using the current MVP

### Step A - establish the input and conflict

Show one genuine selected DOT row and the field satisfying `WEATHER_DELAY > 15 OR LATE_AIRCRAFT_DELAY > 20`.
Show airline, origin, destination and scheduled arrival without displaying the entire CSV record.

Identify the attached scenario and separate these facts:

- Historical source: flight identity, schedule and delay attribution.
- Mock operational state: runway closure interval, fuel, gate bookings, crew schedule and configured operating limits.

Explain one conflict that requires coordination.
For example, the earliest runway slot leads to an unavailable preferred gate, while waiting for that gate consumes fuel and threatens passenger connections.
Historical weather-delay minutes select the row; they do not prove the simulated runway closure occurred.

### Step B - show independent proposals

Start the real workflow.
Show a concise extract from each agent's structured response:

| Role | Useful evidence |
| --- | --- |
| ATC | Proposed slot/runway/route and the traffic constraint motivating it |
| Pilot | Fuel/connection priority and the arrival options it prefers |
| Ground | Gate/crew conflict and an alternative resource assignment |

Show role identity and round number.
One model provider can serve three separate agents; do not imply different providers are required for independence.

Do not replace actual responses with prewritten dialogue.
A live run may choose a different valid option from the rehearsed example.

### Step C - expose one rejected plan

Show a validator result, preferably with numbers from the actual run:

```text
Candidate: <actual candidate ID>
Rule: <actual constraint ID and fixture/policy version>
Measured outcome: <computed value and unit>
Required bound: <configured limit and unit>
Result: REJECTED
```

Suitable examples are insufficient fuel, a closed runway, inadequate separation, a blocked taxiway or an occupied gate.
If no candidate is rejected in the live success run, use a clearly identified saved failure run; do not fabricate a rejection for dramatic effect.

Explain the method boundary: code computes feasibility; the LLM explains priorities and communicates acceptance.

### Step D - show the agreement or truthful alternative

For a consensus result, show the chosen plan, round count and three explicit acceptances tied to the same candidate hash and snapshot.
Explain one observed concession using the actual messages.

If consensus fails, show the actual fallback/escalation status.
A deterministic result must not be described as agent agreement.

Keep human review distinct from agent consensus:

```text
Negotiation: CONSENSUS / FALLBACK / ESCALATED
Operational use: SIMULATION ONLY
Human review: PENDING / APPROVED / REJECTED, if implemented
```

No human is needed during the two negotiation rounds.
A qualified person would review a recommendation before real-world action.
If the app has no review control, state that approval/execution is outside the current MVP; do not display a pretend functional approval.
Existing simulator reservation commits may remain automatic and must be labelled as simulator actions.

### Step E - show a compact before/after comparison

Use actual computed values from the same frozen scenario:

| Metric | Stated baseline | Result | Delta |
| --- | --- | --- | --- |
| Airborne holding, min | Actual value | Actual value | Calculated |
| Modeled fuel burn, kg | Actual value | Actual value | Calculated |
| Missed connections, passengers | Actual value | Actual value | Calculated |
| Crew overtime, min | Actual value | Actual value | Calculated |

Include protected fuel margin and pass/fail constraint evidence beside the comparison.
A trade-off can improve one metric and worsen another; retain both results.
If the baseline is infeasible, label it infeasible rather than calculating misleading benefit percentages.

## 5. Evaluation plan: small, concrete and reproducible

Start with six scenario cases.
Where supported by available profiles, distribute them across at least three genuine qualifying source rows.
If only one row is tested, report that exact coverage rather than implying broader performance.

| Case | Scenario variation | Behavior to inspect |
| --- | --- | --- |
| E1 | Runway disruption with feasible recovery options | Consensus or a truthful fallback; complete trace |
| E2 | Change gate occupancy or crew availability | Recalculated valid allocation; no hardcoded gate choice |
| E3 | Reduce fuel enough to invalidate a previously acceptable hold | Unsafe option rejected; alternative or escalation |
| E4 | No feasible destination or configured alternate action | Explicit escalation with failed constraints |
| E5 | Missing safety-critical input, such as current fuel | Refusal to invent a value; explicit input/planning failure |
| E6 | Provider timeout or malformed agent response | Bounded termination and deterministic fallback when feasible |

These are planned tests, not completed results.
Each case needs a concrete input, scenario version, configured expected invariant, observed outcome and saved run ID.
E1 does not guarantee an LLM will agree; record the outcome actually obtained.

Add no-unanimous-overlap and stale-snapshot cases if already supported by the implementation.
Keep fault injection in test mode visibly separate from live mode.
Contract stubs can verify orchestration behavior, but do not count stub-generated consensus as live-agent performance.

To check input sensitivity, change one operational value and rerun.
Verify that the engine recomputes feasibility; the final plan need not change if the original winner remains best.
Do not force a different answer just to make the demonstration look responsive.

Measure:

- Live consensus within two rounds: count / eligible live runs attempted.
- Fallback and escalation: counts, reasons and denominators.
- Invalid or missing agent responses: count / expected responses.
- End-to-end latency: median and worst observed, with sample size and timeout cases identified.
- Hard violations among committed simulator plans: count / committed plans; do not describe zero observed violations as a proof of real-world safety.
- Holding, modeled fuel, connection and overtime deltas on paired feasible comparisons.

With a small test set, counts are more informative than an unsupported accuracy percentage.
Preserve failed runs and include timeouts in reliability reporting.
Report performance only for the cases and model/provider configuration actually tested.

## 6. Baselines and the question: why use agents?

**Primary comparison:** the existing blueprint's fixed preferred-gate/earliest-feasible-arrival policy on the same scenario.
Describe this as a simplified uncoordinated policy, not a measured reconstruction of real airport practice.

**Useful additional comparison, if time permits:** run the deterministic planner without LLM negotiation.
Reuse the same action catalogue, validators, snapshot and scoring policy for a fair comparison; the existing fallback's different selection policy alone cannot isolate the agents' contribution.

Keep the explanation honest:

- Rules enforce modeled hard limits.
- Deterministic search evaluates permitted schedules.
- Independent agents represent domain priorities, exchange structured proposals, explain concessions and explicitly agree across roles.

If the deterministic planner produces an equally good or better schedule, report that.
The demonstrated agent contribution may be coordination and recorded agreement rather than superior optimisation.
Do not claim privacy-preserving decentralisation when the current central validator sees all domain state.

## 7. Minimal integration work for the existing build

Before changing code, inventory what the original blueprint already supplies.
Reuse `RunResult`, constraint reports, event logs, source provenance, round counts and baseline metrics.

Only add the following if missing and necessary for the demo:

| Small addition | Purpose |
| --- | --- |
| Real/mock/derived labels on displayed facts | Prevent ambiguity about evidence |
| Numerical check result with rule reference | Make one rejection verifiable |
| Three acceptance references for the selected candidate | Make consensus inspectable |
| Compact baseline/result export | Support impact claims |
| Case runner or saved evaluation table | Support honest evaluation |
| Clear simulator/review/execution wording | Preserve human control without changing negotiation |

Keep these additions additive.
Do not replace the agent framework, alter the round protocol, add live feeds, invent new operational capabilities or build new UI infrastructure for this guide.

## 8. Three-minute presentation plan

| Time | Content | Evidence |
| --- | --- | --- |
| 0:00–0:25 | Name the user, disruption and coordination pain | One flight and the scenario conflict |
| 0:25–0:45 | Show real input and synthetic enrichment | Threshold field and source labels |
| 0:45–1:40 | Run negotiation; explain one rejection and concession | Three agents, code check, exact approvals |
| 1:40–2:05 | Explain the result and review boundary | Agreed plan or truthful fallback status |
| 2:05–2:35 | Show before/after and evaluation coverage | Actual metrics and case counts |
| 2:35–3:00 | Show one failure and state the limits | Saved escalation/failure trace and reason |

If the provider is slow, use waiting time to explain the constraint checks rather than extending the presentation.
Prepare a labelled recorded replay or saved run as backup; state immediately when switching away from a live run.

Keep the failure demonstration prepared and brief; it does not need a second full live negotiation.
Finish within three minutes during rehearsal, including transitions.

## 9. Submission and evidence pack

Prepare these from the working build:

1. A reproducible run command or existing app entry point.
2. One complete success trace, if achieved, with three independent live agent acceptances.
3. One failure or escalation trace and a clear reason.
4. A small evaluation table containing actual case results and run IDs.
5. One paired baseline/result comparison with units and assumptions.
6. A short limitations statement: synthetic operational state, small coverage, fixed mock policies and no live operational integration.

Do not fill missing results with example numbers from the implementation blueprint.
Its worked fuel/time scenario illustrates calculations; it is not experimental evidence until the system runs it and records the outcome.

Make a valid working submission before spending remaining time on optional refinements, where the submission rules permit.
Record the actual submission time.
Earlier submission is only 5% of the rubric and does not justify skipping core evidence.

## 10. Likely questions and evidence-backed answers

| Judge's question | What to show or explain |
| --- | --- |
| Why three agents? | Separate calls, distinct domain inputs/priorities and cross-domain acceptance messages |
| Why not just a solver? | Solver/rules handle schedules and checks; agents demonstrate communication, concessions and explicit agreement; show the planner-only comparison if completed |
| What prevents unsafe acceptance? | A failing numerical check excludes the plan before consensus/commit, irrespective of LLM approval |
| What if they never agree? | Two-round limit followed by deterministic fallback or explicit escalation |
| What data is real? | Exact DOT source row and lookups; separate versioned synthetic operational fixtures |
| Is this operationally safe? | It is a simulation with configured rules; no certification or real-world safety validation is claimed |
| How do you know it helps? | Paired scenario outcomes and actual measured latency; broader operational gains remain unvalidated |
| Who decides? | Agents negotiate automatically; qualified personnel retain real-world authority; simulator actions are labelled |

## 11. Final readiness check

The MVP is ready to present when the team can demonstrate the real-data trigger, three independent roles, bounded negotiation, a checkable rejection, a truthful terminal outcome, a baseline comparison and a visible failure.
Any unimplemented capability must be labelled as planned.

This guide is grounded in the supplied challenge and judging rubric.
It adds no externally sourced operational requirements and creates no new claim of measured performance.
