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

- **Scenario** and **flight**: the four backend scenarios, with either the synthetic demo flight or a real disrupted DFW arrival from the US DOT 2015 data, searchable once `bootchicks import-flights` has run (otherwise the verified UA 1590 record).
- **Agents**: fixture agents (no API calls), Claude agents (needs `ANTHROPIC_API_KEY` in the repository's `.env`) or no agents (deterministic planner only).
- **Gate busy periods**: block DFW or DAL gates in half-open minute intervals after the scenario start.
Backwards and overlapping periods are flagged next to the row and block the run; the backend checks again.
- **Agent system prompts**: edit the ATC, Pilot and Ground prompts, or reset each to its default.
Edits are saved in this browser's local storage and sent only for Claude runs; only edited roles are sent.
- **Results**: one card per agent per round, then the proposal board and the decision, laid out in the AeroResolve design from PR #6.
Each agent card shows the constraints it was given, its proposals or votes with rationales, and a live log.
The data comes from `GET /runs/{id}/decisions`, which the app polls while the run is in progress.
- **Replay**: each run plays back one step at a time (a round starting, each agent replying, the proposal board, the result), so even instant fixture runs can be followed.
Every step stays on screen for at least 0.4 s, or 0.8 s when the stage changes; slower live steps show as soon as they arrive.
The page scrolls to the current stage, highlights it, dims the others and animates bits along the connector feeding it.
Scrolling by hand stops the auto-scroll for that run, and **Skip replay** in the top bar shows the whole result at once.

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
