# BootChicks - Multi-Agent Disruption Negotiation Blueprint

Version: 0.1 - backend and simulation scope, 31 October 2026.

## 1. Goal and recommended direction

Build a reproducible simulation in which three independent AI agents negotiate an arrival recovery plan after an airport disruption:

- **ATC:** protect runway separation, taxiway access and sector capacity; improve throughput.
- **Pilot:** protect fuel and aircraft operating limits; reduce airborne delay, turbulence and missed connections.
- **Ground operations:** find compatible gates and available crews; reduce turnaround delay and overtime.

The deliverable is an agreed, executable-within-the-simulator plan, accompanied by structured messages, numerical constraint checks and an auditable consensus record.

**Core design:** three independent LLM agents, one deterministic orchestrator, one shared constraint engine.
Keep the proposed maximum of nine candidate plans.
Replace the final arbitrator LLM with deterministic validation and selection, followed by explicit approval from every domain agent.

The challenge says "under 3 turns."
Target **two communication rounds**.
A round is one simultaneous opportunity for each of the three agents to respond to the same frozen round input.
There are six logical agent responses in a successful run, rather than six negotiation rounds.
Log both counts to make this distinction visible.
Do not claim fewer than three individual messages.

All autonomy is inside a mock operational environment.
The system never issues real flight clearances or communicates with actual airport systems.
Mock limits are configurable scenario assumptions, not certified aviation rules.

## 2. MVP boundaries

Implement one disrupted target flight, one destination airport, one alternate airport, a small fixed set of surrounding flights, 2 runways, 3–5 gates and 2–3 crews.
Surrounding flights are reservation constraints; the MVP cannot silently move them.

Negotiate these concrete decisions:

1. Touchdown time and destination runway.
2. Approved approach option and holding duration.
3. Taxi route and on-block time.
4. Gate and crew assignment.

Landing is the primary negotiated action.
Diversion is supported by a preconfigured alternate action in the deterministic fallback.
Actual route geometry, speed control, altitude changes, multi-airport optimisation and live feeds are outside the MVP.

No UI requirements, frontend implementation, authentication or deployment work are included in this blueprint.
A CLI, JSON files and a small API are sufficient to prove the backend.

## 3. Changes to the initial flow

| Initial idea | Recommended implementation | Reason |
| --- | --- | --- |
| Round 1 only identifies constraints | Round 1 reports domain constraints and proposes up to 3 complete plans | Leaves room for explicit agreement within two rounds |
| Each agent invents arbitrary plans | Agents compose plans from a finite, scenario-owned action catalogue | Prevents fictional gates, routes and aircraft capabilities |
| Self-biased, moderate and conceding plans | Preferred, compromise and concession plans | Concession only affects preferences; hard limits never change |
| Arbitrator chooses from 9 plans | Code checks every plan, calculates outcomes and ranks eligible plans | A persuasive explanation cannot override a failed check |
| Safety check after final arbitration | Validate before voting and again before commit | Agents only approve exact plans with computed evidence |
| Chosen plan equals consensus | All 3 agents explicitly accept the same immutable candidate | Arbitration alone does not demonstrate cross-domain agreement |
| Fallback called a successful negotiation | Separate `CONSENSUS`, `FALLBACK` and `ESCALATED` outcomes | Makes the result truthful and inspectable |

## 4. Input tables: preserve the original CSV headers

Use the three files from the supplied Kaggle dataset.
Preserve the original uppercase column names in raw-input models; use descriptive lowercase names only in normalized operational models.

### 4.1 `flights.csv` - 31 columns

```csv
YEAR,MONTH,DAY,DAY_OF_WEEK,AIRLINE,FLIGHT_NUMBER,TAIL_NUMBER,ORIGIN_AIRPORT,DESTINATION_AIRPORT,SCHEDULED_DEPARTURE,DEPARTURE_TIME,DEPARTURE_DELAY,TAXI_OUT,WHEELS_OFF,SCHEDULED_TIME,ELAPSED_TIME,AIR_TIME,DISTANCE,WHEELS_ON,TAXI_IN,SCHEDULED_ARRIVAL,ARRIVAL_TIME,ARRIVAL_DELAY,DIVERTED,CANCELLED,CANCELLATION_REASON,AIR_SYSTEM_DELAY,SECURITY_DELAY,AIRLINE_DELAY,LATE_AIRCRAFT_DELAY,WEATHER_DELAY
```

### 4.2 `airlines.csv` - 2 columns

```csv
IATA_CODE,AIRLINE
```

Here, `AIRLINE` is the airline name.
In `flights.csv`, `AIRLINE` is the airline code.
Normalize these into `airline_code` and `airline_name` to avoid a join collision.

### 4.3 `airports.csv` - 7 columns

```csv
IATA_CODE,AIRPORT,CITY,STATE,COUNTRY,LATITUDE,LONGITUDE
```

Join the airline lookup using `flight.AIRLINE == airline.IATA_CODE`.
Join the airport lookup twice, using `ORIGIN_AIRPORT` and `DESTINATION_AIRPORT` respectively.
Use `origin_airport` and `destination_airport` aliases in normalized output.

### 4.4 Trigger contract

The workflow receives one complete flight row, its airline lookup and the origin/destination airport lookup rows.
Airport and airline tables are imported once; the trigger carries only the matching rows, not millions of records.

```json
{
 "schema_version": "1.0",
 "flight_row": "object containing the 31 original flight headers",
 "airline_row": "object containing IATA_CODE and AIRLINE",
 "airport_rows": ["origin lookup object", "destination lookup object"],
 "scenario_id": "runway_closure_gate_conflict_v1",
 "seed": 42,
 "mode": "live"
}
```

This is a shape illustration; the actual fields are typed objects, not strings.
Validate lookup keys against the flight row.
Resolve the fallback alternate through the scenario's airport lookup.

Scenario selection and operational enrichment are simulation metadata.
Do not add mock fuel or gate fields to the original CSV schema.

### 4.5 Eligible-row selection and provenance

Mandatory challenge condition:

```python
eligible = (
   (weather_delay is not None and weather_delay > 15)
   or (late_aircraft_delay is not None and late_aircraft_delay > 20)
)
```

The demo selector also requires `CANCELLED == 0`, `DIVERTED == 0`, resolvable origin/destination codes, and the scheduled fields needed for normalization.
These are demo restrictions, not changes to the challenge condition.

Stream `flights.csv` using `csv.DictReader`; the MVP does not need pandas or a database import of the entire file.
Pick the first suitable row in file order for which a complete scenario profile exists.
Save the exact selected row, lookup rows, file SHA-256, CSV line number, filter and scenario version.

If no matching profile exists, report `NO_SUPPORTED_DEMO_ROW`; do not fabricate a DOT record.
If a lookup contains an unfamiliar numeric airport identifier, require an explicit mapping or skip that row with a recorded reason.
Never guess an IATA code.

The source CSVs were not attached to this blueprint request.
No real eligible row has been selected or verified yet.
Selecting and preserving that real row is the first implementation milestone.
A synthetic operational fixture must never be represented as a historical DOT row.

### 4.6 Normalization rules and replay semantics

- Keep airport/airline codes and tail numbers as strings.
  A tail number identifies an aircraft; it does not encode its aircraft type.
- Blank numeric cells become `null`, not zero.
  Reject NaN/infinity.
  Preserve negative arrival/departure delays.
- HHMM fields are clock times, not minute counts: `5` means `00:05`, `1430` means `14:30`.
  Handle `2400` as next-day midnight; reject other invalid values.
- Delay and duration fields are minutes.
  `DISTANCE` remains miles until an explicitly named conversion is needed.
- Configure IANA airport time zones in the operational profiles; the airport CSV does not contain them.
  Build departure time from the flight's service date and origin zone.
  Derive scheduled destination gate arrival from departure plus `SCHEDULED_TIME`, then cross-check local `SCHEDULED_ARRIVAL`.
  Reject unexplained disagreement and ambiguous DST cases in the demo selector.
- Store timezone-aware UTC timestamps internally, with original local values retained in provenance.
  Dates must survive midnight crossings.
- `SCHEDULED_ARRIVAL` is scheduled gate arrival, not touchdown.
  Model touchdown, taxi-in and gate arrival as separate times.
- Use the historical delay fields to select/label the disruption.
  They are retrospective attribution data, not live weather measurements.
  Do not use actual final `WHEELS_ON`, `ARRIVAL_TIME` or `ARRIVAL_DELAY` to tell agents the future outcome.
- In replay, create a documented synthetic clock and current aircraft state around the selected flight.
  One simple mode sets simulated undisturbed gate ETA to scheduled gate arrival plus `max(WEATHER_DELAY, LATE_AIRCRAFT_DELAY, 0)` and derives earliest touchdown using a profile taxi duration.
  This is a demo mapping, not an inference about the real flight.
  Do not add overlapping delay attribution columns together.
- After fixture creation, agents use the same frozen normalized clock and scenario state.
  Preserve the complete raw row for traceability, but give agents only the normalized permitted inputs; historical final outcomes remain in the audit input.

## 5. Operational enrichment: mock database

Use versioned JSON fixtures loaded into typed models.
Key airport infrastructure by `IATA_CODE`; map exact `TAIL_NUMBER` to an aircraft profile, with an explicitly labelled scenario override when no mapping exists.
Do not infer aircraft type from an airline prefix.

Every operational value needs a source label (`mock_fixture`, `scenario_override`, or `derived`), units, a snapshot version and a simulated validity interval.
Missing safety-critical values fail closed.

| Model | Minimum fields | Owner |
| --- | --- | --- |
| Airport profile | IATA code, IANA time zone, runway IDs, taxi network, gates, alternate IDs | Shared |
| Runway | Open/closed intervals, eligible aircraft classes, landing slots, occupancy duration, wind conditions, approach compatibility | ATC |
| Separation policy | Ordered leader/follower wake-class matrix in seconds; explicit mock policy version | ATC |
| Traffic reservation | Flight ID, wake class, runway, touchdown/occupancy times, sector entry/exit, taxi resource intervals | ATC |
| Capacity policy | Arrival limit per rolling 60 minutes, sector concurrency limit | ATC |
| Taxi network | Nodes/edges, travel durations, closure intervals, resource capacities, runway-to-gate paths | ATC |
| Aircraft profile | Exact tail mapping, type label, wake class, gate class, crosswind limit, turbulence limit | Pilot |
| Aircraft state | Current simulated time, fuel kg, earliest approach completion, approach/hold/taxi burn rates | Pilot |
| Fuel policy | Protected landing fuel floor kg, protected on-block floor kg, alternate requirement components and contingency buffer | Pilot |
| Approach option | ID, permitted runways, duration, burn, turbulence severity, valid weather interval | Pilot/ATC |
| Passenger connections | Passenger count, onward boarding deadline UTC, gate transfer durations | Pilot |
| Gate | ID, aircraft compatibility, occupied intervals, buffer minutes, availability windows | Ground |
| Crew | ID, skills, availability intervals, shift end, hard maximum overtime | Ground |
| Turnaround | Aircraft/service minimum duration, service requirements, next departure target, gate occupancy buffer | Ground |
| Alternate option | Airport/runway/gate/crew, route duration/burn, weather, traffic and resource reservations | Shared |

Reserve fuel is a scenario-supplied protected floor with documented components.
Do not assume a universal "45 minutes" rule.
Similarly, do not treat a generic 3–6 NM wake range or an invented category matrix as an operational standard.

Store hard maximum overtime separately from overtime cost.
The first is non-negotiable; the second is an optimisation preference.

## 6. Independent agents and shared services

| Component | Inputs and responsibilities | Must not do |
| --- | --- | --- |
| ATC agent | Flight context, ATC profile, available actions; propose runway/time/route choices and explain throughput trade-offs | Reduce configured separation or invent capacity |
| Pilot agent | Flight context, aircraft/fuel/passenger profile; propose safe arrival choices and connection concessions | Spend protected reserves or change operating limits |
| Ground agent | Flight context, gate/crew/turnaround profile; propose feasible resource choices | Double-book resources or exceed overtime maximum |
| Orchestrator | Deliver messages, freeze rounds, merge outputs, enforce deadlines, invoke validators, collect votes | Impersonate a domain agent's acceptance |
| Constraint engine | Calculate all outcomes and hard checks using authoritative state | Trust an LLM's arithmetic or safety assertion |
| Selector | Choose an exact unanimously approved feasible plan under a published scoring policy | Select a plan rejected by one agent |
| Fallback planner | Enumerate the bounded action catalogue and return a validated deterministic result | Claim agent consensus or relax a hard constraint |

Use distinct system prompts, context objects and model calls for the three roles.
They can share one LLM provider and model.
Independence means separate domain responsibilities and decisions, not necessarily separate vendors or processes.

Round 1 gives each agent its own operational detail plus shared public flight context and the action catalogue.
Round 2 broadcasts the complete structured proposal board, constraint summaries and computed candidate outcomes.
This is the cross-domain communication layer.
No agent directly edits another agent's state.

Domain summaries are communication aids.
The engine always checks the full authoritative state, including a constraint accidentally omitted by an agent.

## 7. Finite plan representation

The scenario engine creates a bounded catalogue of landing slots, approach options, taxi paths, compatible gate IDs and crew IDs.
Catalogue membership is necessary but does not guarantee joint feasibility.

For the MVP, bound deterministic enumeration to 20 landing slots × 2 approaches × 3 taxi paths × 4 gates × 3 crews = 1,440 combinations, plus a small configured alternate catalogue.
Configuration exceeding the bound is rejected rather than truncated silently.

Agents propose up to three action combinations each: `preferred`, `compromise`, `concession`.
Up to nine submitted candidates are normalized and deduplicated.
A concession might accept another gate or several additional holding minutes; it cannot lower a reserve floor.

```json
{
 "candidate_id": "generated-by-server",
 "snapshot_version": "scenario-v1:17",
 "action": "LAND",
 "destination_airport": "scenario-destination",
 "landing_slot_id": "slot-25",
 "approach_option_id": "approach-standard",
 "taxi_path_id": "path-bravo",
 "gate_id": "B2",
 "crew_id": "C2"
}
```

These are illustrative resource IDs.
Use real IDs from the loaded mock profile.
The server derives touchdown time, holding minutes, edge traversal intervals, gate arrival, turnaround start/end, fuel, overtime and connection outcomes.
Agents cannot override derived metrics.

Hash the canonical action fields, schema/policy versions and snapshot version.
Identical actions deduplicate to one candidate while retaining all proposing agents.
The resulting hash is the identity used in votes.
Never modify a voted candidate in place.

## 8. Structured communication contracts

Define Pydantic models for `WorkflowInput`, the three raw CSV records, `NormalizedFlight`, `OperationalSnapshot`, `ActionCatalogue`, `CandidatePlan`, `CheckResult`, `CandidateEvaluation`, `RoundOneResponse`, `RoundTwoResponse`, `ConsensusCertificate`, `RunResult` and `AuditEvent`.

All agent messages use this envelope:

```json
{
 "schema_version": "1.0",
 "run_id": "run-001",
 "snapshot_version": "scenario-v1:17",
 "round": 1,
 "sender": "ATC",
 "recipients": ["PILOT", "GROUND"],
 "message_type": "PROPOSAL",
 "in_reply_to": [],
 "payload": {}
}
```

The server assigns message ID, timestamp and event sequence, verifies sender identity and appends the event.
Do not let the model supply a different sender or snapshot.

**Round 1 payload:** constraint references with `constraint_id`, hard/soft classification and priorities; up to three action combinations; rationale per proposal; requested concessions from other domains.
Hard-constraint values are copied from server state or referenced by ID, never authored by the model.

**Round 2 payload:** one decision for every published feasible candidate, including exact `candidate_id` and `plan_hash`; `ACCEPT` or `REJECT`; preference rank; reason codes; short rationale; references to other agents' proposals and specific concessions accepted.
An empty accepted set is valid and leads toward fallback.
Missing decisions, duplicate ranks, unknown hashes or inconsistent decisions invalidate the response.

An `ACCEPT` is binding for that exact candidate under that exact snapshot, conditional on that candidate being selected and final revalidation succeeding.
Approving multiple candidates permits the deterministic selector to choose any one of them without another communication round.

Use strict JSON output or a single typed response tool.
Reject additional keys, unknown resources, unbounded text and incorrect enum values.
Set explicit maximum lengths and list sizes.
Do not run scripts, shell commands or arbitrary model-generated code.

## 9. Two-round negotiation protocol

### Preparation - deterministic, no negotiation round

1. Validate input, threshold, joins, temporal consistency and scenario completeness.
2. Freeze the operational snapshot and policy versions; construct the action catalogue.
3. Compute a reproducible baseline on the same snapshot.
4. Open the run log and prepare three domain-specific contexts.

### Round 1 - independent proposals

Call the three agents independently and concurrently.
Each reports its constraints and proposes up to three complete action combinations, with explicit preferred/compromise/concession labels.

After all responses arrive, broadcast the structured board.
Normalize, deduplicate and evaluate every candidate against all three domains.
Publish computed costs and pass/fail evidence.
Exclude any candidate failing any hard check.

If a role times out, returns invalid output, or no feasible proposed candidate remains, go directly to deterministic fallback.
Do not manufacture a replacement agent message.

### Round 2 - cross-domain review and conditional acceptance

Each independent agent receives all Round 1 messages and the same immutable evaluated candidate list.
Each evaluates the other domains' constraints, names its concessions and explicitly accepts/rejects every feasible candidate.

The orchestrator computes:

```python
common = feasible_ids & atc.accepted_ids & pilot.accepted_ids & ground.accepted_ids
```

If the intersection is nonempty, select its best candidate using the published scoring rule.
Revalidate against the current snapshot and atomically reserve all simulator resources.
Return `CONSENSUS` only if all three approvals and the commit succeed.

No candidate editing, new counterproposal or new agent call is permitted after Round 2.
If approvals do not intersect, return a deterministic fallback result.
Explain the conflicting preferences in the log.

### Limits and deadlines

- `MAX_NEGOTIATION_ROUNDS = 2`.
- At most three proposals per agent; at most nine submitted candidates.
- One model request per agent per round; disable provider automatic retries for the MVP.
- Proposed starting budget: 12 seconds per round, 30 seconds total, including fallback.
  Measure actual provider latency and make budgets configurable.
- Schema failure is logged and routes to fallback; no hidden repair conversation.
- Cancel outstanding tasks at deadline; record why each expected response is absent.
- Pure code validation, selection and fallback do not constitute another agent communication round.

Model calls are bounded even when the provider is unavailable.
Deterministic fallback must remain runnable without an API key.

## 10. Hard constraints and deterministic calculations

Return a `CheckResult` for every required rule: constraint ID, domain, pass/fail, measured value, required bound, unit, signed margin and source reference.
Missing evidence is a failure, not a warning pass.

### ATC checks

- Runway remains open throughout its required occupancy interval.
- Aircraft class and approach are permitted on that runway.
- Leader/follower separation passes against both adjacent existing movements, using the ordered wake-class matrix.
  Include existing runway occupancy and configured departure reservations.
- Inserting the arrival respects the configured airport-wide rolling 60-minute acceptance rate; check all affected rolling windows, not just the clock hour.
- Inserting its sector interval does not exceed sector concurrency.
- Every taxi edge exists, connects runway to the selected gate, remains open during traversal and has available capacity.
  Waiting is allowed only at configured holding nodes and must be represented in time/fuel calculations.

For the MVP, prebuild landing slots and paths in code, but recheck the combined plan.
An arrival slot and a taxi path that are individually available may still conflict when combined.

### Pilot checks

Use a deliberately simple documented model with consistent kg/min units:

```text
holding_minutes = touchdown_time - earliest_touchdown_for_approach
fuel_at_touchdown = fuel_now
                   - approach_fuel
                   - holding_minutes * hold_burn_kg_per_min
fuel_at_gate = fuel_at_touchdown - modeled_taxi_fuel
```

Require nonnegative holding, approach feasibility and:

```text
fuel_at_touchdown >= protected_landing_floor_kg
fuel_at_gate >= protected_on_block_floor_kg
```

The approach duration already includes the remaining flight phase from the frozen clock.
Never charge that phase twice.
Taxi waiting burns fuel according to the fixture's chosen taxi/idle model.
A route change changes its duration and burn explicitly.

Protected floors document whether alternate/contingency fuel is included; never double-count components or spend them on optional delay reduction.
Validate alternate reachability separately for a diversion action.

Also check crosswind and turbulence against configured aircraft/approach limits, using the scenario conditions applicable at the planned time.
No assumption that historical weather-delay minutes imply a current wind speed.

Connections are normally soft: a passenger makes a connection when on-block time plus deplaning/transfer duration is no later than the configured boarding deadline.
Connection deadlines are not aircraft safety constraints.

### Ground checks

- Gate aircraft class and service requirements match.
- Gate is free for the entire occupation interval, including turnaround and configured buffers.
  Use half-open intervals `[start, end)` consistently.
- Assigned crew has the necessary skills and is available for its entire required service interval, including docking if the fixture requires it.
- Turnaround duration is at least the configured minimum.
- Crew service end is no later than shift end plus maximum allowed overtime.
- Proposed reservations do not conflict with existing gate/crew bookings.
  Missed next-departure targets are soft unless explicitly configured otherwise.

### State consistency

Snapshot age must remain within configured validity.
On commit, compare the version under a resource lock/transaction.
If another run changed it, do not reuse old votes: cancel the attempted commit, log `STALE_SNAPSHOT` and run deterministic fallback on the fresh state.
The MVP does not start a third negotiation round.

## 11. Feasible-plan ranking

Safety is an eligibility gate, never a weighted score.

For eligible plans, compute reproducible costs from state, not LLM ratings.
Normalize each metric with a fixed scenario scale and clamp to `[0, 1]`; store weights and scales with the run.

Suggested starting policy:

```text
ATC cost = 0.6 * slot_delay_cost + 0.4 * taxi_resource_minutes_cost
Pilot cost = 0.6 * airborne_fuel_cost + 0.4 * missed_connection_fraction
Ground cost = 0.4 * gate_wait_cost + 0.3 * overtime_cost
             + 0.3 * next_departure_delay_cost
```

`slot_delay` is relative to earliest approach-compatible touchdown; airborne fuel includes remaining approach and holding.
If no passenger has a connection, missed-connection fraction is zero.

Only rank unanimously accepted candidates.
Select the smallest tuple:

```text
(maximum_of_three_domain_costs,
sum_of_three_domain_costs,
touchdown_timestamp,
candidate_id)
```

This starts with the worst-affected domain and then improves aggregate cost.
It is a declared demo fairness policy, not a claim of globally optimal aviation scheduling.
Agent preference ranks provide negotiation evidence but do not change the frozen scoring rule.

## 12. Deterministic fallback

Fallback is a separate planner using exactly the same hard validators.
It runs on timeout, malformed outputs, no feasible proposals, no unanimous overlap, unavailable LLM, or stale state.

1. Enumerate all permitted destination landing combinations within the configured finite horizon, independently of agent proposals.
2. Validate every enumerated candidate; reject every hard violation.
3. Select lexicographically by airborne fuel burn, touchdown time, missed connections, overtime and canonical plan ID.
   This conservative ordering is fixed and logged.
4. If no destination landing is feasible, enumerate the configured alternate options; validate alternate fuel, weather, arrival capacity, taxi/gate and crew resources before selecting one.
5. Revalidate and atomically commit the chosen simulator reservations.
6. If no validated action exists, return `ESCALATED` with `NO_VALIDATED_PLAN`, failed constraints and a human-review request.
   Do not automatically hold longer, assert an alternate is safe, or invent a clearance.

Use `FALLBACK` for a validated deterministic landing/diversion.
Its consensus certificate is null and agent approvals are not implied.
Terminal paths remain bounded even if nothing is feasible.

## 13. Worked negotiation fixture

This is a **synthetic operational example**, not a selected DOT record.
Attach it to a qualifying real row during implementation and express times relative to its replay clock `T`.

Fixture assumptions:

- At `T`, fuel on board is 6,000 kg; standard remaining approach takes 20 minutes and burns 1,200 kg.
- Holding burns 40 kg/min; an 8-minute taxi path burns 200 kg.
- Protected landing floor is 4,000 kg; protected on-block floor is 3,800 kg.
- One runway is unavailable until `T+22`.
  Configured traffic and separation permit slots at `T+25` and `T+35`.
- Direct taxi path Alpha is blocked.
  Path Bravo is open and takes 8 minutes.
- B2 is compatible and free from `T+30`; A1 is compatible and free from `T+43`.
- C2 can service B2 from `T+30` and ends its shift at `T+85`.
  C1 can service A1 from `T+43` and ends its shift at `T+80`.
  Both allow at most 10 minutes of overtime.
- Gate occupation and crew service last 45 minutes in this fixture; buffers are zero.
  Connections require gate arrival by `T+40`, after accounting for the fixture's transfer allowance.
- Other aircraft, weather and sector limits are configured so the two stated open-runway slots pass.
  Add explicit reservations rather than treating their feasibility as an LLM judgment.

| Candidate | Touchdown / gate arrival | Fuel touchdown / gate | Outcome |
| --- | --- | --- | --- |
| Earliest preferred attempt | `T+20 / T+28`, B2, Bravo | 4,800 / 4,600 kg | Reject: runway closed and gate not yet free |
| Ground-preferred A1 | `T+35 / T+43`, A1, Bravo | 4,200 / 4,000 kg | Feasible; misses stated connections and incurs 8 minutes crew overtime |
| Cross-domain compromise B2 | `T+25 / T+33`, B2, Bravo | 4,600 / 4,400 kg | Feasible; connections retained, no crew overtime |
| Excessive holding attempt | `T+45 / T+53` | 3,800 / 3,600 kg | Reject: both protected fuel floors breached |

Round 1 should show conflicting preferred actions and at least one feasible compromise among the up-to-nine candidates.
Round 2 should show ATC accepting the runway/route choice, the pilot accepting five minutes of holding, and ground accepting B2 instead of its preferred A1.
Configure prompts and fixture incentives to make this plausible; do not hardcode live agent votes.

Compare the feasible A1 baseline against the feasible B2 compromise on the same snapshot: 10 minutes less airborne holding, 400 kg less modeled fuel burn, gate arrival 10 minutes earlier, and 8 fewer minutes of crew overtime.
Label these as scenario-model outcomes.
A live run can select another unanimously accepted feasible candidate; tests should prove the rules, not require an LLM to produce an exact sentence or choice.

## 14. Baseline, metrics and audit output

Before negotiation, run a fixed uncoordinated policy: use the scenario's preferred gate and earliest fully feasible arrival serving it.
If that policy is infeasible, report baseline infeasibility; do not manufacture improvement percentages against an unsafe baseline.

Record for baseline and result: touchdown/gate times, airborne holding, modeled fuel burn, both fuel margins, missed connections, overtime, turnaround end, next-departure delay and each hard-check result.
Report deltas using the same model.
Do not equate saved fuel with measured real-world emissions or infer network-wide delay savings from a one-flight demo.

Persist per-run events in SQLite, with JSONL export.
Events include input provenance, snapshot/policy hashes, prompt versions, provider/model ID, sanitized inputs and responses, proposals, rejection evidence, broadcasts, acceptances, ranking, fallback reason, resource commit and terminal result.
Assign monotonic event sequence numbers; concurrent arrival order must not change candidate identity or selection.

Store concise decision rationales, not hidden chain-of-thought.
Keep API keys and authorization headers out of logs.
Include `mode` and response origin (`live`, `stub`, `recorded_replay`) on each response.

The final result contains:

```text
run_id, schema_version, status, terminal_reason
source_provenance, snapshot_version, policy_version
rounds_used, logical_agent_responses, provider_requests, latency_ms
selected_plan, computed_outcomes, hard_constraint_report
consensus_certificate or null
fallback_reason or null
baseline_metrics, improvement_metrics, audit_event_reference
```

A `ConsensusCertificate` contains the selected hash, snapshot/policy versions, three accepting agent IDs with their message IDs, final validation-report hash and commit event ID.
`CONSENSUS` requires all fields.
Any failed commit produces a different terminal result.

## 15. Recommended implementation stack

Use Python, Pydantic for contracts, a direct LLM SDK adapter, `asyncio` for the three independent calls per round, standard-library SQLite/JSON and pytest.
Add FastAPI as the thin HTTP trigger/result layer after the core CLI works.

Start with an explicit Python state machine rather than adding an orchestration framework.
The workflow is small, fixed and bounded.
A future LangGraph integration can wrap the same services if checkpointing/branching later warrants it; it is not an MVP dependency.

Define one provider-neutral interface:

```python
async def respond(agent_role, round_number, typed_context, response_schema):
   ...  # one independent model request; typed result or explicit error
```

Choose the provider for which the team already has API access, configure the model ID through environment settings, and pin the tested SDK version.
If using Claude, direct Messages API structured tools are sufficient; a coding-agent SDK with shell access is unnecessary for this negotiation task.

`stub` mode returns clearly labelled fixtures for development; `live` mode makes real independent calls.
Stub votes can test certificates but must never appear as a live multi-agent demonstration.
A recorded replay is separately labelled.

## 16. Suggested repository layout

```text
BootChicks_Blueprint.md
pyproject.toml
README.md
.env.example
data/raw/                      # user-provided CSVs; exclude large files from git
data/fixtures/                 # selected real row + lookup/provenance records
data/scenarios/                # versioned mock airport/aircraft/crew profiles
src/bootchicks/
   schemas.py                 # shared typed contracts
   ingestion.py               # header validation, eligibility, joins, normalization
   scenario.py                # mock enrichment, frozen clock, action catalogue
   agents.py                  # separate role prompts and response handling
   providers.py               # live/stub/replay adapters
   constraints.py             # authoritative ATC/pilot/ground checks
   metrics.py                 # computed costs, baseline comparison
   negotiation.py             # two-round state machine
   selection.py               # unanimous intersection and deterministic ranking
   fallback.py                # bounded enumeration with shared validators
   store.py                   # events, idempotency, resource reservations
   api.py                     # thin FastAPI endpoints
   cli.py                     # select-row, run, export
tests/
   test_ingestion.py
   test_constraints.py
   test_negotiation.py
   test_fallback.py
   test_commit.py
```

This is a suggested starting structure.
Keep domain functions small and pure; split files only as needed.
No distributed message broker or separate microservice per agent is required.

API shape: `POST /runs` accepts the typed trigger with an `Idempotency-Key`, creates the job and returns `202` plus `run_id`.
`GET /runs/{id}` returns current/final state; `GET /runs/{id}/events` returns ordered events.
For the MVP, use one worker and serialize resource commits.
Reusing a key with a different payload returns `409`; identical retries return the same run.
Mark jobs interrupted by restart as failed rather than silently rerunning and double-booking resources.

## 17. Orchestrator pseudocode

```python
async def negotiate(request):
   run = validate_and_open_run(request)
   snapshot, catalogue = build_complete_snapshot(run)
   baseline = compute_baseline(snapshot, catalogue)

   # All steps below share the run deadline; any exception is logged.
   first = await parallel_role_calls(round=1, snapshot=snapshot,
                                     catalogue=catalogue)
   if not all_three_valid(first):
       return fallback_and_finish(run, reason="ROUND_1_FAILURE")

   candidates = canonicalize_and_deduplicate(first.proposals)
   evaluations = validate_all(candidates, snapshot)
   feasible = only_fully_feasible(evaluations)
   if not feasible:
       return fallback_and_finish(run, reason="NO_FEASIBLE_PROPOSALS")

   second = await parallel_role_calls(round=2, snapshot=snapshot,
                                      proposal_board=first,
                                      evaluations=evaluations)
   if not all_three_valid(second):
       return fallback_and_finish(run, reason="ROUND_2_FAILURE")

   common = unanimous_accepted_candidates(second, feasible)
   if not common:
       return fallback_and_finish(run, reason="NO_UNANIMOUS_PLAN")

   winner = select_by_frozen_policy(common, snapshot)
   committed = revalidate_and_commit_atomically(winner, snapshot.version)
   if not committed:
       return fallback_and_finish(run, reason="COMMIT_REVALIDATION_FAILED")

   return finish_consensus(run, winner, second, baseline, committed)
```

The actual implementation must pass explicit run state rather than relying on globals.
Fallback obtains fresh state when necessary, observes the remaining total deadline, and never calls the LLM.
Log and terminate if its commit fails; do not recurse indefinitely.

## 18. Build order for Codex

1. **Data and scenario foundation:** validate all three header sets, select a genuine eligible row, preserve provenance, implement normalized time handling, create the complete mock operational snapshot.
2. **Deterministic simulation:** implement plan expansion, all hard validators, outcome calculations, baseline, bounded fallback and atomic simulator reservations.
   Demonstrate this without an LLM first.
3. **Agent contracts:** implement three distinct prompts/adapters and typed Round 1/Round 2 responses; use stubs to verify orchestration.
4. **Live negotiation:** connect one configured provider; run independent calls, broadcast the structured board, collect exact approvals and generate consensus certificates.
5. **Backend demo surface:** CLI and API, ordered event export, baseline comparison, explicit fallback demo and documented commands.

Each milestone should leave a runnable checkpoint.
Codex should implement the backend only, follow existing repository conventions if present, and avoid adding frontend scaffolding.

## 19. Acceptance checks

| Test | Required evidence |
| --- | --- |
| Real-data trigger | Preserved source row meets `WEATHER_DELAY > 15 OR LATE_AIRCRAFT_DELAY > 20`; all three table schemas validated |
| Threshold boundaries | Exactly 15 / 20 do not qualify; nullable fields handled without converting unknown into evidence |
| Three independent agents | Separate role/model requests and prompt identities; no single call impersonating all roles |
| Cross-domain exchange | Round 2 inputs contain all Round 1 messages and computed cross-domain candidate evidence |
| Consensus | Three explicit acceptances of one exact plan/snapshot; at most two communication rounds |
| Hard-limit enforcement | Closed runway, insufficient separation, blocked taxiway, insufficient fuel, incompatible/busy gate and excessive crew overtime each rejected |
| Boundary correctness | Test fuel just below/at floor, separation just below/at threshold, rolling-hour boundary, midnight and interval endpoints |
| No unsafe compensation | Excellent soft score cannot rescue a hard-failing plan |
| No agreement | Disjoint acceptance sets yield fallback, never an invented approval |
| Provider failure | Timeout, malformed output and rate-limit failure terminate within budget and use deterministic fallback |
| Fallback without AI | No provider/key required; same input and snapshot produce the same validated action |
| No feasible action | Returns `ESCALATED`; no fabricated holding/diversion safety claim |
| State changed | Old votes cannot commit against a new snapshot; no duplicate gate/crew/runway reservations |
| Reproducible selection | Same candidates/votes/state yield the same winner regardless of response completion order |
| Provenance separation | Historical source facts, synthetic operational assumptions and live agent outputs are distinguishable |
| Outcome comparison | Delta metrics use the same feasible baseline/model; infeasible baseline reported explicitly |

Prefer focused numerical tests of the actual invariants and integration tests of terminal paths.
Do not test exact LLM wording or rely on live calls in the automated test suite.

## 20. Decisions adopted for v0.1

- Two negotiation rounds, not a third arbitrator-agent round.
- Three independent agents; deterministic code coordinates and enforces limits.
- Up to three plans per role; agents may submit fewer when distinct valid options do not exist.
- Exact unanimous acceptance; voting binds hashes and snapshot versions.
- One target flight; surrounding schedules remain fixed.
- Versioned JSON operational fixtures; SQLite run/audit persistence.
- Safety-critical unknowns reject planning; no universal reserve/wake assumptions.
- Deterministic fallback can land, divert through validated alternate fixtures, or escalate.
- Python core with direct provider adapter; thin FastAPI API after CLI.
- No UI scope yet.

Revisit only if implementation evidence warrants it: provider/model choice and actual measured timeouts; destination profile selected from the supplied source data; fixed scoring scales/weights; exact fixture parameters.
These are configuration decisions and must be versioned, not made ad hoc by an LLM.

## 21. Sources and evidence limits

- Challenge requirements and initial design: supplied in the project prompt.
- Source dataset: [US DOT - 2015 Flight Delays and Cancellations, Kaggle](https://www.kaggle.com/datasets/usdot/flight-delays/data?select=flights.csv).
- Published ingestion example for the 2015 files, including flight/airport columns: [VerticaPy joins documentation](https://www.vertica.com/python/old/workshop/data_prep/joins/).
  The actual downloaded CSV header rows remain the implementation authority; fail clearly on mismatch.
- Framework references: [FastAPI](https://fastapi.tiangolo.com/), [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), [Claude tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

The operational constraints, cost weights, fuel model and worked scenario in this blueprint are proposed simulation design decisions.
They are not sourced regulatory limits or claims that the DOT files contain live operational state.
