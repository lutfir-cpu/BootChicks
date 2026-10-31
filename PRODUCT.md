# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Hackathon judges and the BootChicks team are equally primary users.
Judges watch a live demo or try the app briefly.
They need to grasp quickly that three independent Claude agents (ATC, Pilot, Ground) negotiated one arrival plan and that Python, not the model, enforced the hard checks.
The team uses the same interface day to day to tune agent system prompts, scenarios and gate busy periods, rerun negotiations and inspect the results.

## Product Purpose

BootChicks Arrival desk replays a hypothetical airport arrival disruption, such as a runway closure that forces a gate change.
In round 1 the three role agents each propose up to three complete landing plans; in round 2 each votes on every plan that passed the hard checks.
The interface has two equal jobs.
It makes the round-by-round negotiation and the final checked plan easy to follow and convincing.
It also makes it quick to edit scenarios and prompts, run experiments and see what changed.
Success means a judge can follow one run end to end without explanation, and a team member can change a prompt or assumption and rerun it in seconds.

## Positioning

Agents negotiate, but deterministic Python checks decide.
Every candidate is validated against fuel floors, separation, runway and taxi conflicts, gates, crews and airport capacity, and a plan only counts as **Consensus** when all three roles accept the same validated version and its resources are committed.
When negotiation fails, the deterministic fallback is labelled as a fallback, never as agent consensus, and a run with no valid plan is escalated to a human.

## Operating Context

- A React web app in `frontend/` on top of the FastAPI backend in `src/bootchicks`; `bootchicks serve` serves both locally.
- Used live on a laptop or projector during judging, and day to day by the team on their own machines.
- Three agent modes: fixture agents (deterministic, no API calls), Claude agents (three independent structured Claude calls per round) and no agents (deterministic planner only).
- Inputs: four backend scenarios, the synthetic demo flight or any supported real disrupted DFW arrival from the US DOT 2015 data (the verified UA 1590 record when no flights are imported), gate busy periods and per-role system prompts.
- Outputs: the outcome, chosen plan and baseline comparison, both negotiation rounds, the checked proposal board, every hard check of the chosen plan, and JSON/JSONL audit exports.

## Capabilities and Constraints

- Stack: React with TypeScript and Vite for the web app (confirmed 2026-10-31, replacing the earlier Streamlit demo), Python with FastAPI and SQLite for the backend.
- Status vocabulary: **Consensus**, **Fallback**, **Escalated**, **Failed**.
- Each web run uses a fresh simulated environment; agent prompt edits are kept in browser local storage.
- No accounts or hosted deployment; the server binds to localhost.
- All operational values are labelled simulation assumptions, not real clearances or approved aviation guidance.
- Not available in the web app: free-form editing of fuel, runways and other scenario values, which the earlier Streamlit demo had.

## Brand Commitments

- Product name: BootChicks; the web app is titled **Arrival desk**, with the tagline "Three perspectives. One checkable arrival plan."
- Voice: plain, precise and careful about claims. Assumptions, simulations and fallbacks are always labelled as such.

## Evidence on Hand

- Backend scenarios in `data/scenarios/blueprint_v1.json` and challenge airport capacity limits in `data/constraints/airport_capacity.csv`.
- A genuine historical trigger row (United 1590, ORD to DFW, 1 January 2015) in `data/fixtures/real_trigger.json`.
- `bootchicks import-flights` catalogues the 17,310 supported disrupted DFW arrivals in the 2015 data, each with its raw row, lookups and source file hashes.
- There are no real users, testimonials, measured savings or operational validations; future work must not imply any.

## Product Principles

1. The negotiation is the story: show who proposed what, why, and how the roles converged.
2. Checks over claims: the deterministic validation behind every outcome stays visible and is never overstated.
3. Fast iteration: editing a prompt or assumption and rerunning should be quick, and stale results are flagged.
4. Honest labels: simulation, offline mode, fallback and assumptions are always named.
