import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fetchOptions, followRun, startRun } from './api'
import { busyPeriodErrors, toOccupancies, type BusyPeriod } from './busyPeriods'
import { AgentCard } from './components/Agents'
import { ProposalBoard } from './components/Board'
import { DecisionCard } from './components/Decision'
import { BranchConnector, MergeConnector } from './components/Layout'
import {
  AirportState,
  BusyPeriodsEditor,
  FlightRecord,
  PromptEditor,
  ScenarioControls,
  type FlightSource,
} from './components/Setup'
import { STATUS_TEXT } from './labels'
import type { RunView } from './trace'
import { ROLES, type DecisionLog, type Mode, type Options, type Role, type RunRequest, type RunResult } from './types'

const PROMPT_STORAGE_KEY = 'bootchicks.rolePrompts'
const LIVE_BUDGET = { round_timeout_seconds: 60, total_timeout_seconds: 150 }

type RunPhase =
  | { kind: 'idle' }
  | { kind: 'running'; log: DecisionLog | null }
  | { kind: 'error'; message: string }
  | { kind: 'done'; result: RunResult; log: DecisionLog; fingerprint: string }

export default function App() {
  const [options, setOptions] = useState<Options | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    fetchOptions().then(setOptions, (error: Error) => setLoadError(error.message))
  }, [])

  if (loadError) {
    return (
      <Shell>
        <div className="card notice" role="alert">
          <h1>Cannot load the simulator</h1>
          <p>{loadError}</p>
        </div>
      </Shell>
    )
  }
  if (!options) {
    return (
      <Shell>
        <p className="page-loading">Loading scenarios...</p>
      </Shell>
    )
  }
  return <Desk options={options} />
}

function Shell({ status, onTrace, children }: { status?: ReactNode; onTrace?: () => void; children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="top-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              ✈
            </span>
            <span>Arrival desk</span>
          </div>
          {status}
          {onTrace && (
            <button className="trace-btn" type="button" onClick={onTrace}>
              View audit log
            </button>
          )}
        </div>
      </header>
      <main className="workflow">{children}</main>
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
  const traceRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Keep only edited prompts, so changed defaults reach users who never edited them.
    const edited = Object.fromEntries(
      ROLES.filter((r) => prompts[r] !== options.default_prompts[r]).map((r) => [r, prompts[r]]),
    )
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
      // Only live runs use prompts. One Claude round takes over 12 s, the backend's default round budget.
      ...(mode === 'live'
        ? { role_prompts: editedPrompts, ...LIVE_BUDGET }
        : { role_prompts: {} }),
      ...(source === 'sample' ? { trigger: { ...options.sample_trigger, scenario_id: scenarioId } } : {}),
    }
  }, [scenarioId, mode, busy, prompts, source, options])
  const fingerprint = JSON.stringify(request)

  async function run() {
    setPhase({ kind: 'running', log: null })
    try {
      const id = crypto.randomUUID()
      // A fresh environment per run, so earlier commits never block a new attempt.
      const { run_id } = await startRun({ ...request, environment: `ui-${id.slice(0, 12)}` }, id)
      const { result, log } = await followRun(run_id, (log) => setPhase({ kind: 'running', log }))
      setPhase({ kind: 'done', result, log, fingerprint })
    } catch (error) {
      setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  function loadDemo() {
    setScenarioId(options.scenarios[0].id)
    setSource('synthetic')
    setMode('stub')
    setBusy([])
  }

  function showTrace() {
    traceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    traceRef.current?.focus({ preventScroll: true })
  }

  const runView: RunView | null =
    phase.kind === 'done'
      ? { log: phase.log, result: phase.result }
      : phase.kind === 'running' && phase.log
        ? { log: phase.log, result: null }
        : null

  const row = options.sample_trigger.flight_row
  const flight = source === 'sample' ? `${row.AIRLINE} ${row.FLIGHT_NUMBER}` : 'Demo flight'
  const [statusText, statusTone] =
    phase.kind === 'running'
      ? ['Negotiating', 'running']
      : phase.kind === 'done'
        ? [STATUS_TEXT[phase.result.status].title, phase.result.status.toLowerCase()]
        : phase.kind === 'error'
          ? ['Could not start', 'failed']
          : ['Ready', 'idle']
  const status = (
    <span className={`scenario-status status-${statusTone}`} aria-live="polite">
      {flight} · {scenario.airports[0].iata_code} · {statusText}
    </span>
  )

  return (
    <Shell status={status} onTrace={showTrace}>
      <section aria-labelledby="input-title">
        <article className="card input-card">
          <div className="input-heading">
            <div>
              <p className="kicker">Input</p>
              <h1 id="input-title">Disruption scenario</h1>
            </div>
            <button className="demo-btn" type="button" onClick={loadDemo}>
              Demo
            </button>
          </div>
          <div className="input-columns">
            <ScenarioControls
              options={options}
              scenarioId={scenarioId}
              source={source}
              mode={mode}
              onScenario={setScenarioId}
              onSource={setSource}
              onMode={setMode}
            />
            <FlightRecord options={options} source={source} />
            <AirportState scenario={scenario} />
          </div>
          <div className="input-columns two">
            <BusyPeriodsEditor scenario={scenario} rows={busy} onChange={setBusy} />
            <PromptEditor defaults={options.default_prompts} prompts={prompts} onChange={setPrompts} />
          </div>
          <div className="input-footer">
            <div className="run-bar">
              <button type="button" className="primary-btn" disabled={!canRun} onClick={run}>
                {phase.kind === 'running' ? 'Negotiating...' : 'Run negotiation'}
              </button>
              {!busyValid && <p className="field-error">Fix the gate busy periods first.</p>}
              {busyValid && mode === 'live' && !promptsValid && (
                <p className="field-error">Every agent needs a system prompt.</p>
              )}
              {phase.kind === 'error' && (
                <p className="field-error" role="alert">
                  The run could not start. {phase.message}
                </p>
              )}
            </div>
            <p className="note">Simulation with mock operational data. Not operational guidance.</p>
          </div>
        </article>
      </section>

      <section aria-labelledby="round-one-title" aria-busy={phase.kind === 'running'}>
        <h2 className="turn-title" id="round-one-title">
          Round 1 - Independent proposals
        </h2>
        <BranchConnector />
        <div className="agent-grid">
          {ROLES.map((role) => (
            <AgentCard key={role} role={role} round={1} run={runView} />
          ))}
        </div>
      </section>

      <section aria-labelledby="board-heading">
        <h2 className="turn-title" id="board-heading">
          Python checks - Proposal board
        </h2>
        <MergeConnector />
        <ProposalBoard run={runView} />
      </section>

      <section aria-labelledby="round-two-title">
        <h2 className="turn-title" id="round-two-title">
          Round 2 - Votes on every evaluated plan
        </h2>
        <BranchConnector />
        <div className="agent-grid">
          {ROLES.map((role) => (
            <AgentCard key={role} role={role} round={2} run={runView} />
          ))}
        </div>
      </section>

      <section aria-labelledby="decision-heading">
        <h2 className="turn-title" id="decision-heading">
          Decision and commit
        </h2>
        <MergeConnector />
        <DecisionCard
          run={runView}
          stale={phase.kind === 'done' && phase.fingerprint !== fingerprint}
          traceRef={traceRef}
        />
      </section>
    </Shell>
  )
}
