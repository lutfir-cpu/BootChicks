# Deviations from the blueprint and demo guide

This compares the repository with [BLUEPRINT.md](BLUEPRINT.md) (v0.1) and [DEMO_CRITERIA.md](DEMO_CRITERIA.md).
It covers `main` at `7776bbd` (after PR #3, airport capacity).
It is a companion to [blueprint-coverage.md](blueprint-coverage.md), which lists what conforms.

## Verification basis

- `python -m pytest -q`: 132 passed.
- `ruff check .`: clean.
- `bootchicks run --trigger data/fixtures/real_trigger.json --mode stub` on a fresh database: `CONSENSUS`, 2 rounds, 6 logical responses, 0 provider requests.
  Selected B2 / Bravo / C2 at T+25 with 5 minutes of holding and 4,600 / 4,400 kg fuel.
  Against the A1 baseline it saved 10 min holding, 400 kg fuel, 10 min to gate, 8 min overtime and 20 connections.
  This matches blueprint section 13.
- `insufficient_fuel` and `no_gate` escalated with `NO_VALIDATED_PLAN`.
  `diversion` returned `FALLBACK` to DAL.
  `--mode fallback` returned `FALLBACK` (B2).
- The local database `data/runs/bootchicks.sqlite` holds no runs, so there is no recorded live or replay evidence.

## Summary

The backend follows the blueprint's architecture closely.
That includes the three raw schemas, the genuine trigger row, two rounds, exact-hash votes, the deterministic validators, fairness selection, fallback/escalation, atomic SQLite commits, the CLI/API and the audit log.
The deviations fall into four groups:

1. **Evidence gaps:** there is no live-model run, only one real source row, and none of the evaluation tooling the demo guide asks for.
2. **Behavioural gaps:** a few checks are weaker than specified or missing.
   For example, gate-wait cost is always zero, alternate-fuel reachability is not checked separately, and turnaround minimum is only enforced through the capacity CSV.
3. **Scope additions:** the blueprint does not ask for the airport-capacity CSV checks, the gate-occupancy inputs, editable prompts or the React frontend.
4. **Structural and naming differences:** these are harmless but worth knowing when reading the blueprint against the code.

## 1. Evidence gaps

| Blueprint / guide requirement | Current state | Where |
| --- | --- | --- |
| Section 18 milestone 4 and guide sections 4 and 9: a live negotiation with three real independent acceptances | The Claude adapter exists and is tested only against a mocked SDK. No live run is recorded and no saved trace is checked in. The README says a real smoke test "remains separate". | `src/bootchicks/providers.py`, `tests/test_blueprint_negotiation.py::test_claude_adapter_makes_six_separate_typed_requests` |
| Guide section 5: spread cases across at least three genuine qualifying rows | There is one genuine row (UA 1590 ORD-DFW, 2015-01-01, CSV line 3121). The selector only supports DFW with DAL as alternate, so no other destination can be selected. | `ingestion.py:207`, `data/fixtures/real_trigger.json` |
| Guide section 5: E1-E6 case runner or saved evaluation table, with run IDs and denominators | There is no case runner, saved evaluation table or aggregate metrics (consensus count, invalid-response count, median/worst latency). E1, E3 and E4 exist as CLI scenarios. E2 is possible through `--gate-occupancies`. E5 and E6 are only exercised in pytest, with no labelled fault-injection mode in the CLI or API. | `cli.py`, `tests/` |
| Guide section 6: a planner-only comparison using the same scoring policy | Not implemented. The only deterministic planner is the fallback, which uses the fuel-first `fallback_rank` rather than `fairness_rank`, so it cannot isolate the agents' contribution. | `constraints.py:570-592` |
| Guide section 4 Step D: `Operational use: SIMULATION ONLY` and a human-review status | `RunResult` has no operational-use or review field. Human review only appears as `human_review_required: true` inside the `NO_VALIDATED_PLAN` event. | `schemas.py:467`, `negotiation.py:349` |
| Guide section 7: compact baseline/result export | `improvement_metrics` and the full `baseline` evaluation are in the JSON result. There is no compact table or report output. | `constraints.py:595` |
| Guide sections 4 and 9: backup recorded replay | Replay mode exists, but no recording is checked in or prepared. | `providers.py:175` |

## 2. Behavioural deviations

### 2.1 Ingestion and replay

- **Time zones live in code, not in operational profiles (section 4.6).**
  `ingestion.py:39-58` keeps a hardcoded `TIMEZONES` dict.
  The `Airport.timezone` field in the scenario JSON exists but normalization does not use it.
- **Earliest touchdown uses a hardcoded 8-minute taxi (section 4.6, "a profile taxi duration").**
  `ingestion.py:159` subtracts a constant 8 minutes.
  It happens to equal the Bravo/Charlie path duration, but it is not read from the profile.
- **Destination is hardcoded to DFW/DAL (section 4.5).**
  The selector rejects every non-DFW row as `NO_DESTINATION_OR_ALTERNATE_PROFILE` before it checks lookups.
  It does not discover which profiles exist.
- **Skipped rows are recorded as reason counts, not per row (section 4.5).**
  `Provenance.skipped_reasons` is a `Counter`.
  This is enough for transparency, but it does not identify individual lines.
- **Provenance lacks a scenario version (section 4.5, "filter and scenario version").**
  `scenario_id` is on `WorkflowInput` and `profile_version` is on the snapshot, but neither is in `Provenance`.
- **The alternate lookup travels inside provenance.**
  `airport_rows` holds exactly origin and destination.
  The DAL row is carried in `provenance.raw_lookups["alternate"]`, and `load_snapshot` requires it there (`scenario.py:55-61`).
- **The trigger's default mode is `stub` and there is an extra `fallback` mode.**
  The blueprint's illustration uses `"mode": "live"` and lists `live`/`stub`/`recorded_replay`.
  `Mode` adds `fallback` (`schemas.py:21`).
  This is reasonable, but it is an extension.

### 2.2 Operational fixture (sections 5 and 13)

- **Source labels, units and validity are per category, not per value (section 5).**
  `operational_provenance` is one string per category.
  The whole snapshot shares one validity interval (`clock` to `valid_until`).
  Units are implied by field-name suffixes.
  The `derived` label is never used structurally.
- **Both destination runways are closed at T.**
  R1 is closed until T+22 and R2 is closed for the whole window (`blueprint_v1.json:91-95`).
  The blueprint only says "one runway is unavailable until T+22".
  As a result, the second runway never contributes options.
- **Background traffic is minimal.**
  There are only two arrivals (T-5 and T+60) with runway and arrival reservations.
  There are no departure, sector or taxi reservations for other flights.
  Section 10's "configured departure reservations" and adjacent-movement wake checks are therefore only exercised in tests, not in the demo fixture.
- **The A1 path is called Charlie, not Bravo.**
  The section 13 table lists "A1, Bravo".
  In the fixture, Bravo leads to B2 and Charlie (also 8 minutes) leads to A1.
  The numbers are identical.
- **Extra resources were added.**
  The fixture has gate C3 (H-class, incompatible), gate D4 (free from T+90) and crew C3.
  This is within the 3-5 gates / 2-3 crews bound.
- **Aircraft profile, aircraft state and fuel policy are merged into one `Aircraft` model.**
  The blueprint lists them as three models.
  The fields are all present.
- **Crews carry a `gate_ids` assignment.**
  The blueprint does not specify this.
  It is enforced in `CREW_SKILLS`.
- **The runway class check uses `aircraft.gate_class`.**
  There is no separate runway eligibility class (`constraints.py:159`).

### 2.3 Constraint engine (section 10)

- **Gate wait is always zero (section 11 Ground cost).**
  `Outcomes.gate_wait_min=0` is hardcoded (`constraints.py:518`).
  The 0.4-weighted `gate_wait_cost` term therefore never contributes to the Ground cost.
  This follows from having no surface-wait actions, but the weight is effectively dead.
- **No waiting at holding nodes (section 10 ATC).**
  Taxi paths have no wait action.
  This is documented in the README, but it narrows the blueprint.
- **Alternate reachability is not checked separately (section 10 Pilot).**
  A `DIVERT` uses the same `LANDING_FUEL` / `ON_BLOCK_FUEL` floors as a destination landing, including the 1,500 kg "alternate allowance" component.
  There is no distinct reachability or alternate-fuel check, despite the fixture's `fuel_policy_notes` saying it is "evaluated separately".
- **The turnaround minimum is only enforced when capacity data is loaded (section 10 Ground).**
  `CAPACITY_MIN_TURNAROUND` comes from the challenge capacity CSV (`constraints.py:233-243`).
  The scenario has no turnaround-minimum field of its own.
  The `Store` always loads capacities, so CLI and API runs are covered, but direct `load_snapshot` use without capacities skips the check.
- **Weather is static per runway.**
  Crosswind is one value per runway with one validity window, not "conditions applicable at the planned time".
- **Snapshot validity is checked against the plan horizon, not snapshot age.**
  `SNAPSHOT_VALIDITY` checks that the plan ends before `valid_until`.
  There is no wall-clock age check on the frozen snapshot.
- **No neutral domain for system checks.**
  `CheckResult.domain` is limited to `ATC`/`PILOT`/`GROUND`, so `EXACT_PLAN_IDENTITY`, `FLIGHT_NOT_ALREADY_COMMITTED` and `SNAPSHOT_VALIDITY` are filed under ATC.

### 2.4 Protocol, contracts and limits (sections 8 and 9)

- **Some text fields are unbounded (section 8).**
  Items in `requested_concessions`, `reason_codes`, `proposal_references`, `accepted_concessions` and `ConstraintReference.constraint_id` have list-size limits but no string `max_length` (`schemas.py:416-440`).
  Only `rationale` has a maximum length (1,000).
- **"Inconsistent decisions" is not defined or checked (section 8).**
  Completeness, ranks, hashes and references are validated.
  Nothing checks, for example, that accepted candidates rank above rejected ones.
- **The cross-domain reference rule is stricter than the blueprint.**
  Every vote must cite at least one other role's proposal message (`negotiation.py:109-113`).
  The blueprint asks for references but does not make them mandatory per vote.
- **Agents author the hard/soft classification.**
  Constraint IDs are checked against the server's list, but the agent's `classification` is not compared with the server's own classification.
- **Live runs from the web app use longer budgets than the blueprint's starting budget.**
  A real round 1 Claude call took about 12.4 s, just over the 12 s round budget, so every agent timed out.
  The web app sends 60 s per round and 150 s in total for Claude runs; the CLI keeps 12 s and 30 s by default.
  The provider's own HTTP timeout is 120 s, the largest allowed round budget, so the asyncio round deadline alone enforces the configured limit.
- **There is no named `MAX_NEGOTIATION_ROUNDS` constant (section 9).**
  The limit is structural, and `RunResult` rejects `rounds_used > 2`.
- **The stale-snapshot reason is merged.**
  Section 10 asks for `STALE_SNAPSHOT`, and the section 17 pseudocode uses `COMMIT_REVALIDATION_FAILED`.
  The implementation emits a single `STALE_SNAPSHOT_OR_COMMIT_REVALIDATION_FAILED` (`negotiation.py:504`), so the two cases cannot be told apart in the result.
- **There are extra terminal reasons.**
  `PROVIDER_OR_PROTOCOL_ERROR`, `TOTAL_DEADLINE_EXCEEDED`, `DETERMINISTIC_ONLY`, `FALLBACK_COMMIT_FAILED` and `FALLBACK_ERROR` extend the blueprint's set.
  The status enum adds `FAILED` for interrupted or crashed jobs.
- **Round 2 shares full domain state, not summaries.**
  `cross_domain_constraints` broadcasts each role's complete domain context.
  This is consistent with the guide's "do not claim privacy-preserving decentralisation".
- **Round 2 includes failed candidates.**
  Deterministic checks classify each candidate as `SAFE`, `REQUIRES_AUTHORIZATION` or `SAFETY_BLOCKED` under `mock-operational-review-v1`.
  Agents can conditionally support failed candidates, but only `SAFE` unanimous plans can be committed.

### 2.5 Fallback (section 12)

- **Escalation evidence omits alternates.**
  When nothing is feasible, `NO_VALIDATED_PLAN` records failed checks for destination actions only (`negotiation.py:333`).
  The alternate options that were also rejected are not recorded.
- **Conditionally supported failures carry a separate review report.**
  `RunResult.selected_plan` and `RunResult.evaluation` remain `None` because no plan was committed.
  `RunResult.review_recommendation` carries the failed evaluation, required action and three supporting message references.

### 2.6 Stub agent

- **The stub carries fixture knowledge.**
  It skips path `Alpha` by name and picks B2/C2 or A1/C1 directly (`providers.py:84-112`).
- **The stub supports every candidate using its deterministic status.**
  It accepts safe candidates, supports authorization candidates if authorized and supports safety-blocked candidates if remediated.
  Stub consensus therefore never exercises disagreement.
  Disagreement is covered by pytest providers instead.
  This is acceptable for a labelled stub, but it is not evidence of negotiation.

## 3. Scope additions not in the blueprint

| Addition | Notes |
| --- | --- |
| React frontend in `frontend/` | Section 2 and section 18 exclude UI work. It is a client of the backend API only and shows the blueprint's two-round protocol; it has no negotiation logic of its own. `bootchicks serve` serves the built app at `/`. |
| Challenge airport-capacity CSV | `data/constraints/airport_capacity.csv` and `capacity.py` import versioned synthetic limits into SQLite. This adds the checks `CAPACITY_ACTIVE_RUNWAYS`, `CAPACITY_GATE_TOTAL`, `CAPACITY_MIN_TURNAROUND`, `CAPACITY_RUNWAY_OPERATIONS` and `CAPACITY_SPARE_GATES`. |
| User-defined gate occupancies | `RunRequest.gate_occupancies` and `--gate-occupancies` inject extra gate reservations relative to the scenario clock. |
| Extra API endpoints and fields | `GET /airport-capacities`, `GET /airport-capacities/{iata_code}` and `GET /options`. `POST /runs` also accepts a `RunRequest` wrapper as well as a bare `WorkflowInput`. `RunRequest.environment` starts a run in its own simulated environment so earlier commits do not block it. |
| Synthetic failure scenarios | `insufficient_fuel`, `no_gate` and `diversion` are code-level overrides in `scenario.py:70-83`, not separate versioned scenario files. |
| Editable prompts | `RunRequest.role_prompts` overrides the live system prompt per role. The prompts used are recorded in `ROUND_INPUT`, and agent messages carry `blueprint-agents-v3+custom-<hash>` when edited; defaults are `blueprint-agents-v3`. |

## 4. Structural and naming differences

| Blueprint | Implementation |
| --- | --- |
| `OperationalSnapshot` | `Snapshot` |
| `ActionCatalogue` Pydantic model | A plain dict from `scenario.catalogue()`; not a typed model |
| Action fields `destination_airport`, `landing_slot_id`, `approach_option_id` | `airport`, `landing_slot` (a UTC timestamp, not a slot ID), `approach_id` |
| Snapshot version like `scenario-v1:17` | `<environment_id>:v<n>` |
| Result fields `computed_outcomes`, `hard_constraint_report`, `baseline_metrics` | `evaluation.outcomes`, `evaluation.checks`, `baseline` (a full `CandidateEvaluation`) |
| Envelope authored as the message | The model returns only `sender`, `snapshot_version` and the payload. The server builds the envelope (recipients, message type, `in_reply_to`, mode, origin, model, prompt version) in the event. `run_id` is on the event, not in the payload. |
| `agents.py`, `metrics.py`, `selection.py`, `fallback.py` | Not present. Prompts are in `providers.py`. Costs, ranking and improvement are in `constraints.py`. Intersection and fallback are in `negotiation.py`. `capacity.py` was added. |
| `tests/test_fallback.py`, `tests/test_commit.py` | Covered inside `tests/test_blueprint_negotiation.py`. Test files use a `test_blueprint_*` prefix, plus the capacity tests. |
| `BootChicks_Blueprint.md` at the root | Now `docs/BLUEPRINT.md`. `DEMO_CRITERIA.md` still refers to the old name. |

## 5. Acceptance checks (section 19) needing attention

Most rows in section 19 have a direct test.
These are thin or indirect:

- **Provider failure, rate limit:** simulated with a generic `RuntimeError`, not the Anthropic SDK's `RateLimitError`.
- **No unsafe compensation:** covered only by `fairness_rank` raising on an infeasible evaluation (`test_closed_runway_and_taxi`).
  No test pits a hard-failing plan with an excellent soft score against a feasible one in a full run.
- **Outcome comparison, infeasible baseline:** no test asserts that `improvement_metrics` is `None` and that the `BASELINE` event marks `infeasible: true` when the preferred-gate policy fails.
- **Three independent agents:** proven only with a mocked SDK.
  There is no live evidence (see section 1).

## 6. Suggested priorities

Ordered by the demo guide's rubric weight and the effort each takes:

1. Run and save at least one live negotiation and one live failure trace, plus a recorded replay backup.
2. Add an E1-E6 case runner that writes a small evaluation table with run IDs and counts.
3. Add `operational_use: SIMULATION_ONLY` and a human-review status to `RunResult`, and put the failed constraints into escalated results.
4. Fix the behavioural gaps: separate the alternate-fuel/reachability check, distinguish `STALE_SNAPSHOT`, add string length limits, read the taxi duration and time zones from the profile, and either remove the gate-wait weight or model gate wait.
5. Resolved: the Streamlit frontend and its legacy protocol were replaced by a React client of the backend.
