import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, fetchEvents, fetchOptions, startRun, waitForRun } from './api'
import { busyPeriodErrors, toOccupancies, type BusyPeriod } from './busyPeriods'
import { AuditLinks, Checks, Outcome, PlanSummary, Timeline } from './components/Results'
import {
  BusyPeriodsEditor,
  FlightSourcePicker,
  ModePicker,
  PromptEditor,
  ScenarioPicker,
  type FlightSource,
} from './components/Setup'
import { readNegotiation } from './negotiation'
import { ROLES, type AuditEvent, type Mode, type Options, type Role, type RunRequest, type RunResult } from './types'

const PROMPT_STORAGE_KEY = 'bootchicks.rolePrompts'

type RunPhase =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'error'; message: string }
  | { kind: 'done'; result: RunResult; events: AuditEvent[]; fingerprint: string }

export default function App() {
  const [options, setOptions] = useState<Options | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    fetchOptions().then(setOptions, (error: Error) => setLoadError(error.message))
  }, [])

  if (loadError) {
    return (
      <Shell>
        <div className="load-error" role="alert">
          <h2>Cannot load the simulator</h2>
          <p>{loadError}</p>
        </div>
      </Shell>
    )
  }
  if (!options) {
    return (
      <Shell>
        <p className="loading">Loading scenarios...</p>
      </Shell>
    )
  }
  return (
    <Shell>
      <Desk options={options} />
    </Shell>
  )
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>Arrival desk</h1>
          <p className="tagline">Three perspectives. One checkable arrival plan.</p>
        </div>
        <p className="disclaimer">Simulation with mock operational data. Not operational guidance.</p>
      </header>
      {children}
    </div>
  )
}

function loadPrompts(defaults: Record<Role, string>): Record<Role, string> {
  try {
    const saved = JSON.parse(localStorage.getItem(PROMPT_STORAGE_KEY) ?? '{}') as Partial<Record<Role, string>>
    return Object.fromEntries(
      ROLES.map((role) => [role, typeof saved[role] === 'string' ? saved[role] : defaults[role]]),
    ) as Record<Role, string>
  } catch {
    return defaults
  }
}

function Desk({ options }: { options: Options }) {
  const [scenarioId, setScenarioId] = useState(options.scenarios[0].id)
  const [source, setSource] = useState<FlightSource>('synthetic')
  const [mode, setMode] = useState<Mode>('stub')
  const [busy, setBusy] = useState<BusyPeriod[]>([])
  const [prompts, setPrompts] = useState(() => loadPrompts(options.default_prompts))
  const [phase, setPhase] = useState<RunPhase>({ kind: 'idle' })

  useEffect(() => {
    // Keep only edited prompts, so changed defaults reach users who never edited them.
    const edited = Object.fromEntries(ROLES.filter((r) => prompts[r] !== options.default_prompts[r]).map((r) => [r, prompts[r]]))
    localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(edited))
  }, [prompts, options.default_prompts])

  const scenario = options.scenarios.find((s) => s.id === scenarioId) ?? options.scenarios[0]
  const busyValid = Object.keys(busyPeriodErrors(busy)).length === 0
  const promptsValid = ROLES.every((role) => prompts[role].trim())
  const canRun = busyValid && (mode !== 'live' || promptsValid) && phase.kind !== 'running'

  const request = useMemo((): Omit<RunRequest, 'environment'> => {
    const editedPrompts = Object.fromEntries(
      ROLES.filter((role) => prompts[role] !== options.default_prompts[role]).map((role) => [role, prompts[role]]),
    )
    return {
      scenario_id: scenarioId,
      mode,
      gate_occupancies: toOccupancies(busy),
      // Prompts only affect live runs; leaving them out keeps fixture runs comparable.
      role_prompts: mode === 'live' ? editedPrompts : {},
      ...(source === 'sample' ? { trigger: { ...options.sample_trigger, scenario_id: scenarioId } } : {}),
    }
  }, [scenarioId, mode, busy, prompts, source, options])
  const fingerprint = JSON.stringify(request)

  async function run() {
    setPhase({ kind: 'running' })
    try {
      const id = crypto.randomUUID()
      // A fresh environment per run, so earlier commits never block a new attempt.
      const { run_id } = await startRun({ ...request, environment: `ui-${id.slice(0, 12)}` }, id)
      const state = await waitForRun(run_id)
      const events = await fetchEvents(run_id)
      if (!state.result) throw new ApiError('The run finished without a result.')
      setPhase({ kind: 'done', result: state.result, events, fingerprint })
    } catch (error) {
      setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  return (
    <main className="desk">
      <aside className="setup" aria-label="Run setup">
        <ScenarioPicker scenarios={options.scenarios} value={scenarioId} onChange={setScenarioId} />
        <FlightSourcePicker options={options} value={source} onChange={setSource} />
        <ModePicker options={options} value={mode} onChange={setMode} />
        <BusyPeriodsEditor scenario={scenario} rows={busy} onChange={setBusy} />
        <PromptEditor defaults={options.default_prompts} prompts={prompts} mode={mode} onChange={setPrompts} />
        <div className="run-bar">
          <button type="button" className="primary-button" disabled={!canRun} onClick={run}>
            {phase.kind === 'running' ? 'Negotiating...' : 'Run negotiation'}
          </button>
          {!busyValid && <p className="field-error">Fix the gate busy periods first.</p>}
          {busyValid && mode === 'live' && !promptsValid && (
            <p className="field-error">Every agent needs a system prompt.</p>
          )}
        </div>
      </aside>
      <section className="results" aria-label="Results" aria-busy={phase.kind === 'running'}>
        <ResultArea phase={phase} fingerprint={fingerprint} mode={mode} />
      </section>
    </main>
  )
}

function ResultArea({ phase, fingerprint, mode }: { phase: RunPhase; fingerprint: string; mode: Mode }) {
  if (phase.kind === 'running') {
    return (
      <div className="placeholder" role="status">
        <h2>Negotiating</h2>
        <p>
          {mode === 'live'
            ? 'Waiting for three independent Claude agents. This takes up to 30 seconds.'
            : 'Running the agents and checks.'}
        </p>
      </div>
    )
  }
  if (phase.kind === 'error') {
    return (
      <div className="placeholder error" role="alert">
        <h2>The run could not start</h2>
        <p>{phase.message}</p>
      </div>
    )
  }
  if (phase.kind === 'idle') return <HowItWorks />
  const view = readNegotiation(phase.events)
  return (
    <>
      <Outcome result={phase.result} stale={phase.fingerprint !== fingerprint} />
      <PlanSummary result={phase.result} view={view} />
      <Timeline result={phase.result} view={view} />
      {phase.result.evaluation && <Checks checks={phase.result.evaluation.checks} />}
      <AuditLinks runId={phase.result.run_id} />
    </>
  )
}

function HowItWorks() {
  return (
    <div className="placeholder">
      <h2>How a run works</h2>
      <ol className="how">
        <li>
          <strong>Round 1.</strong> ATC, Pilot and Ground each propose up to three complete landing plans.
        </li>
        <li>
          <strong>Python checks.</strong> Every proposal is tested against hard rules: fuel floors, separation,
          runway and taxi conflicts, gates, crews and airport capacity. Agents cannot override a failed check.
        </li>
        <li>
          <strong>Round 2.</strong> Each role votes on every feasible plan. A plan wins only if all three accept the
          same exact version.
        </li>
        <li>
          <strong>Commit.</strong> The winner is revalidated and its resources booked. Without agreement, a
          deterministic fallback picks a valid plan or escalates to a human.
        </li>
      </ol>
      <p className="hint">Choose a scenario and run the negotiation.</p>
    </div>
  )
}
