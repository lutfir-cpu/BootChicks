# BootChicks

A reproducible, two-round airport-disruption negotiation backend.
Independent ATC, Pilot and Ground agents propose complete actions, review a shared proposal board and explicitly vote on exact candidate hashes.
Python enforces hard constraints; SQLite records evidence and atomically reserves simulated resources.

This implements the supplied v0.1 backend blueprint.
Every operational limit is a labelled mock assumption.
No real clearances are issued and no airport systems are contacted.

## Start with the verified real-data fixture

Python 3.11+ on macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
bootchicks run --trigger data/fixtures/real_trigger.json --mode stub --idempotency-key first-demo
```

The small checked-in trigger is a genuine source row: United flight 1590, ORD to DFW, service date 1 January 2015, CSV line 3121.
It includes the original 31 fields, matching airline/airport rows, original string values and SHA-256 hashes of all three source CSVs.
Its large historical delay crosses midnight in the explicitly synthetic replay mapping.
Aircraft type, current fuel, closures, paths, gates, crews and passenger connections are scenario assumptions, not facts about that flight.

`stub` uses clearly labelled deterministic fixture agents and makes no paid calls.
The expected worked result is `CONSENSUS`, two rounds and six logical agent responses, with a committed runway/taxi/gate/crew allocation.
Against the same feasible baseline, the fixture saves 10 minutes of holding, 400 kg of modeled airborne fuel, 10 minutes to gate and eight minutes of overtime.
These are simulator outcomes, not measured airline savings.

The database defaults to `data/runs/bootchicks.sqlite`.
Repeating an identical idempotency key returns the saved run.
A new key is a new attempted operation in the same simulated environment; a flight that has already committed cannot be booked again.
Use a separate database file for an independent replay, rather than silently resetting existing reservations.

## Failure and fallback demonstrations

```sh
bootchicks run --scenario insufficient_fuel --mode stub --database data/runs/fuel.sqlite
bootchicks run --scenario no_gate --mode stub --database data/runs/gates.sqlite
bootchicks run --scenario diversion --mode stub --database data/runs/diversion.sqlite
bootchicks run --mode fallback --database data/runs/no-model.sqlite
```

The first two escalate with `NO_VALIDATED_PLAN`.
Diversion validates a configured DAL alternate, including fuel, weather, capacity, paths and ground resources, before returning `FALLBACK`.
Deterministic-only mode does not require a model or API key.
A fallback never carries a consensus certificate.

For Claude, copy `.env.example` to `.env`, set your API key and an available model, then use `--mode live`.
The tested Anthropic SDK is pinned in `pyproject.toml`.
Six independent async Messages requests are the successful two-round maximum; provider retries and repair conversations are disabled.
Live output is never substituted with fixture votes.

Starting budgets are 12 seconds per round and 30 seconds overall, including preparation/fallback; CLI flags `--round-timeout` and `--total-timeout` configure them.
Outstanding role tasks are cancelled at the round deadline.
An expired total budget escalates without claiming an unvalidated action.
These are application deadlines, not latency guarantees for an external provider.

## Data ingestion

The original public dataset is [US DOT 2015 Flight Delays and Cancellations on Kaggle](https://www.kaggle.com/datasets/usdot/flight-delays).
Raw downloads are excluded from Git.

```sh
mkdir -p data/raw
curl -fL 'https://www.kaggle.com/api/v1/datasets/download/usdot/flight-delays' -o data/raw/flight-delays.zip
python -m zipfile -e data/raw/flight-delays.zip data/raw
bootchicks select-row --data-dir data/raw --output data/fixtures/selected_trigger.json
```

All three exact header sets are checked.
Flights stream through `csv.DictReader`; airports and airlines are small keyed lookups.
Selection preserves the first suitable row in file order with `WEATHER_DELAY > 15 OR LATE_AIRCRAFT_DELAY > 20`, `CANCELLED == 0`, `DIVERTED == 0`, resolvable lookups, usable schedules and a complete supported destination profile.
The initial destination profile is DFW, with DAL as its alternate.
Explicit origin/destination IANA zones are configured in `ingestion.py`; unfamiliar numeric airport IDs and unsupported profiles are skipped with recorded reasons, never guessed.

Blank numeric cells remain null; nonfinite numbers are rejected.
HHMM values are parsed as local clock times, including 2400.
Departure is localized explicitly, arrival is derived from scheduled duration and cross-checked against destination local time.
Ambiguous/nonexistent DST times are rejected.
All operational timestamps are aware UTC.

Historical delay categories select and label the replay.
The synthetic undisturbed gate ETA is scheduled gate arrival plus the maximum of the two delay categories, then an assumed eight-minute taxi-in determines earliest touchdown.
Historical actual outcomes remain only in audit provenance; agent contexts never receive final `WHEELS_ON`, `ARRIVAL_TIME` or `ARRIVAL_DELAY` values.
Tail numbers are preserved exactly; an explicitly labelled aircraft-profile override is used instead of guessing aircraft type.

## Negotiation and deterministic simulation

- **Preparation:** validate and freeze the profile, build the bounded catalogue and calculate the same-model baseline.
- **Round 1:** three independent role requests, each returning up to three complete preferred/compromise/concession actions.
Code assigns hashes, deduplicates at most nine proposals, checks every domain and publishes the board.
- **Round 2:** each role receives every proposal and the same evaluated feasible set, then accepts/rejects every candidate with exact hashes, unique ranks, cross-domain references and explicit concessions.
- **Selection:** intersect all three accepted sets.
Among unanimous feasible candidates, minimize worst domain cost, then total cost, touchdown and candidate ID.
Scales and weights are frozen in the scenario.
No third round or post-vote candidate editing is allowed.
- **Commit:** under a SQLite write transaction, compare the snapshot/version, rerun every hard check, reserve all resources, create the certificate and persist the final result together.
Changed state invalidates old votes and invokes deterministic fallback against fresh state.

The versioned `data/scenarios/blueprint_v1.json` fixture configures two destination runways, four gates, three crews, two approach options, three taxi paths and one alternate.
The catalogue rejects a configuration exceeding 1,440 combinations per airport instead of truncating it.
Paths structurally connect a runway and gate, so not every Cartesian combination is a permitted action.

Checks include full runway occupancy/closure intervals; aircraft and approach compatibility; ordered leader/follower wake gaps; all affected rolling-hour arrival windows; sector concurrency; connected taxi edges, closures and capacities; approach and taxi fuel; separate protected touchdown/on-block floors; crosswind/turbulence validity; full gate occupation and buffers; crew skills, service intervals, bookings and maximum overtime.
Half-open intervals are used throughout.
Paths have no surface-wait action in this version; waiting is never inserted implicitly.

Fuel floors contain documented mock components.
Those components are already included in the floor and are not charged again.
Connection loss, overtime cost and next-departure delay are preferences, while configured fuel/separation/overtime maxima remain hard constraints.
Each check records its source reference, units, measured value, bound and margin where numeric.

Fallback independently enumerates destination options under the same validators, then the configured alternate if necessary.
Its fixed ordering is airborne fuel, touchdown, missed connections, overtime and plan ID.
Resource commits still require revalidation.
No feasible action means escalation and a human-review flag, never an invented hold or diversion.

## Local API

```sh
bootchicks serve --port 8000 --database data/runs/api.sqlite
```

Open [interactive API documentation](http://127.0.0.1:8000/docs).
The server binds only to localhost.
This MVP has no authentication or deployment scope.

- `POST /runs` requires `Idempotency-Key`, accepts either a complete `WorkflowInput` trigger or a `RunRequest` wrapper and returns HTTP 202 with a run ID.
The wrapper can select a labelled synthetic scenario or contain `trigger`, `mode` and deadline settings.
- `GET /runs/{id}` returns queued/running/terminal state and the saved result.
- `GET /runs/{id}/events` returns ordered events; `?format=jsonl` exports JSONL.
- Identical same-key retries return the same run; a different payload with that key returns HTTP 409.
Invalid inputs return 422, unknown runs 404.

Run one worker per database.
A local process lock enforces ownership of restart recovery, and SQLite transactions serialize simulator commits.
Interrupted queued/running jobs are marked failed on restart and are not silently re-executed.
A CLI run cannot take ownership of the same database while its API worker is active; submit through that API or choose another file.

## Audit, replay and tests

```sh
bootchicks export RUN_ID --format jsonl --output data/runs/events.jsonl
bootchicks export RUN_ID --format json --output data/runs/result.json
python -m pip install -e '.[dev,legacy-ui]'
python -m pytest -q
ruff check .
```

Events include source provenance, snapshot/policy hashes, model and prompt identities, sanitized role contexts, proposals, evaluated evidence, broadcasts, votes, selection, resource commits and terminal status.
Sequence numbers are monotonic per run and completion order cannot change selection.
Secrets and raw provider errors are not logged.
The consensus certificate binds exact plan/state/policy, three distinct acceptance message IDs, final validation hash and commit event ID.

For a recorded replay, set `BOOTCHICKS_REPLAY_FILE` to a JSONL export and use `--mode recorded_replay` against a fresh database.
Replay retains exact plan/state hashes and is labelled separately from live/stub responses; audit message references are remapped to the new run's event IDs.
Mismatched state or incomplete recordings fail closed into fallback.

Tests exercise the genuine selected row, all three schemas, strict thresholds, DST/midnight, fuel/separation/capacity/interval boundaries, unsafe plans, complete vote sets, cross-domain references, stale state, competing runs, cancellation, idempotency, restart recovery, HTTP export and deterministic replay.
They mock provider traffic and do not require a paid API key.
A real live-model smoke test remains separate.

## Existing Streamlit demo

Browse the [app screenshots and PR embed Markdown](docs/screenshots/README.md).

The original single-candidate web demo remains available for reference; it does not implement the new proposal-board protocol.
Its instructions are in [the legacy demo guide](docs/legacy-streamlit.md).
Install `.[legacy-ui]` to run it.
The blueprint backend is the CLI/API above; no new frontend scaffolding was added.
