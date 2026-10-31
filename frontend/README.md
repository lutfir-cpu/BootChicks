# BootChicks - Arrival desk

A local hackathon MVP for Challenge #2: three independent Claude roles negotiate a landing time and gate after an assumed runway closure.
No database, hosted service or agent framework is needed.

## Start

The Streamlit frontend lives in this `frontend/` folder.
Install it from the repository root with Python 3.11 or newer, then start it from this folder so `.streamlit/config.toml` is applied:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[legacy-ui]'
cd frontend
streamlit run app.py
```

The app opens at http://localhost:8501.
Start in **Offline simulation**: the default case agrees in two rounds after changing from G1 to G2.
This mode uses deterministic role simulators, explicitly labelled in the interface and exports.
It is useful for testing the workflow and is not a substitute for demonstrating the three real Claude calls.

To use Claude, copy `.env.example` to `.env` in the repository root, put your API key there, choose a structured-output-capable model available to your account, restart the app and select **Claude agents**.
Never commit `.env`.
Credentials are not included in downloads.
Each round makes three independent role calls in parallel.
Responses use Anthropic's structured-output SDK interface and are validated locally.
Model-generated explanations are decision summaries, not human reasoning ground truth.

## Demo flow

1.
Choose **Gate change after runway closure** and run the negotiation.
The initial candidate lands at minute 20 and reaches the original gate at minute 28; that gate is occupied until minute 40.
Ground proposes G2, then all roles evaluate the complete revised plan.
2.
Set the round limit to one: the outcome becomes **Fallback recommendation**, not negotiated consensus.
3.
Choose **Insufficient fuel** or **No compatible gate** to demonstrate a visible failure.
4.
Upload `data/sample_flights.csv` to try the importer.
Its rows and airline identifiers are entirely fictional.
Or use the organiser's Challenge #2 CSV, select an eligible row and retain or edit the labelled operational assumptions.
5.
Download the scenario and replay audit as JSON.
Changing settings keeps the previous result visible with a stale-input warning.
Only **Run negotiation** calls the agents.

## Inputs and rules

Download a full scenario JSON in the sidebar, or start from `data/sample_scenario.json`.
Uploading scenario JSON takes precedence over imported CSV metadata.
Intervals are half-open `[start, end)` and all times are integer minutes relative to replay start; no timestamp or timezone reconstruction is attempted.
A background runway reservation's start is its operation start for the configured start-to-start separation check.

The three bundled JSON scenarios are in `data/`.

**Airport capacity** shows the challenge-supplied synthetic limits for the selected airport, read from the same SQLite table as the backend (see the repository README).
The app uses `BOOTCHICKS_DATABASE`, resolved from the repository root, or `data/runs/bootchicks.sqlite` there.
Choosing an airport raises the default turnaround to that airport's minimum if needed.
Runs then also check modeled runway and gate totals, minimum turnaround, rolling-hour runway operations and the spare-gate allowance for gate changes.

**Gate busy periods** replace the old `start:end` text field for gates.
Each row picks a configured gate and an occupied-from and occupied-until minute; a period ending at minute 28 allows gate-in at minute 28.
Unknown gates, periods that do not end after they start and overlapping periods on the same gate show an error naming the row, and block the run.
All operational values are assumed.
A CSV provides only historical metadata and delay categories.
Eligibility is strictly `WEATHER_DELAY > 15` or `LATE_AIRCRAFT_DELAY > 20`; header casing, common 2015 flight columns and BTS camel-case delay fields are supported.
CSVs are parsed in 50,000-row chunks and at most 200 eligible rows are displayed.
Uploads are limited to 1 GB; smaller extracts are preferable.
Uploaded data and completed results stay in local process/session memory, with no database.
Browser reloads or app restarts can reset session results, so download important runs.

Fuel feasibility is:

```text
holding_minutes = proposed_landing - nominal_arrival
fuel_after_holding = onboard_fuel - holding_minutes * holding_burn
fuel_after_holding >= remaining_plan_fuel_requirement + additional_buffer
```

The remaining-plan requirement must already include approach, landing, taxi and any protected allowances appropriate to the assumed scenario.
Taxi duration is fixed across all gates/runways in v1.
This is a simplified fuel model, not an operational flight-planning calculation.
Missing fuel values can be represented by JSON `null` or cleared numeric inputs; no agreement is possible until mandatory inputs are present.

Mandatory checks cover airport capacity limits, runway closure/occupancy, a configurable start-to-start separation gap, fuel, gate compatibility and full gate occupancy, static handling availability, derived timings and state versions.
Aircraft/runway performance suitability, taxi-route availability, detailed staffing schedules, weather legality and actual wake categories are assumed, not validated.
There is no diversion or emergency-handling model.
A failure means no feasible option **within the configured replay assumptions and the next 60 minutes**, not that no real-world safe action exists.

## Agent prompts

Each role has its own system prompt, shown under **Agent system prompts** in tabs for ATC, Pilot and Ground.
The defaults are defined in `prompts.py`.
Edit a prompt to change the instructions that role receives on the next Claude run.
**Reset to default** restores that role's original prompt; it is disabled while the prompt is unchanged.
Edits last for the browser session and are not saved to disk.
A blank prompt blocks Claude runs until it is filled in or reset.
Offline simulation ignores prompts.
The prompts used by a Claude run are included in the downloaded replay, and the result lists which roles used edited prompts.
Changing a prompt after a Claude run marks that result as stale.
The scenario JSON is always sent separately as the user message, so an edited prompt cannot change scenario facts or bypass the Python checks.

## Coordination

Three role prompts own ATC, Pilot and Ground concerns.
Every response references the exact candidate and state version.
Acceptance cannot contain a plan modification.
All three must accept and every Python check must pass before the result is **Agreed**.
Changes create a new candidate version and require fresh approvals.

Default budget: two rounds, configurable from one to three.
This is an implementation definition of a round, not a claim that the organisers define "turn" the same way.
The interface counts rounds, validated agent responses and submitted API attempts separately.
SDK retries are disabled; calls have a 25-second request timeout.
Timeout, authentication, malformed/stale responses or an unusable counterproposal end negotiation and invoke a deterministic fallback.
`NEED_INFORMATION` instead stops with **Missing information**.

Counterproposals may change landing minute, runway or gate only.
Each is assembled into a complete plan and checked again.
The fallback enumerates minute-by-minute options from nominal arrival through nominal arrival + 60, ranking by least holding, then keeping the original gate, then runway/gate identifiers.
It cannot override a mandatory check and never implies agent consensus.
The simulation state is frozen during a run; editing inputs starts a new replay when submitted.

## Tests

From the repository root:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```

Frontend tests live in `frontend/tests`.

Tests use fake responses and never require an API key.
They cover end-to-end Streamlit interactions, rerun persistence, independent structured provider calls, constraint boundaries, unsafe counters, stale approvals, provider failures, round budgets and CSV errors.
A real Claude call needs credentials and is intentionally separate from repeatable tests.

## References

- [Challenge datasets](https://drive.google.com/drive/u/1/folders/13h0JZnSqhYTX3rV8dGDGy5AiwaADQvJR)
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [EUROCONTROL A-CDM specification](https://www.eurocontrol.int/sites/default/files/2025-01/eurocontrol-specification-for-acdm.pdf)

This prototype supports reviewing hypothetical decisions.
Its assumed rules and values are not approved operational aviation guidance.
