# Arrival desk frontend

React and TypeScript single-page app for the BootChicks backend, built with Vite.
It talks only to the backend's HTTP API; all negotiation, checks and commits happen in `src/bootchicks`.

## Develop

Start the API in one terminal from the repository root:

```sh
bootchicks serve --port 8000
```

Then start the dev server in another:

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.
The dev server forwards `/options`, `/runs` and `/airport-capacities` to the API on port 8000.

For a single-process setup, run `npm run build` and `bootchicks serve` serves `frontend/dist` at `/`.

## What the app does

- **Scenario** and **flight**: the four backend scenarios, with either the synthetic demo flight or the verified UA 1590 record (US DOT, 1 January 2015).
- **Agents**: fixture agents (no API calls), Claude agents (needs `ANTHROPIC_API_KEY` in the repository's `.env`) or no agents (deterministic planner only).
- **Gate busy periods**: block DFW or DAL gates in half-open minute intervals after the scenario start.
Backwards and overlapping periods are flagged next to the row and block the run; the backend checks again.
- **Agent system prompts**: edit the ATC, Pilot and Ground prompts, or reset each to its default.
Edits are saved in this browser's local storage and sent only for Claude runs; only edited roles are sent.
- **Results**: outcome, chosen plan and its comparison with the baseline, round 1 proposals, the checked proposal board, round 2 votes with rationales, the decision and commit, every hard check of the chosen plan, and links to the audit trail.

Each run uses a new `environment`, so previous commits never block it.
Changing any input after a run marks the result as stale until it is run again.

## Checks

```sh
npm run typecheck
npm run lint
npm test
npm run build
```

Tests use [Vitest](https://vitest.dev) and Testing Library against recorded backend responses in `src/test/fixtures`.
Regenerate those from real stub runs after backend changes, from the repository root:

```sh
python frontend/scripts/export_fixtures.py
```
