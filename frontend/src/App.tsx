import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type Ref } from 'react'
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
import { STEP_MS, useFollowStage, usePlayback } from './playback'
import { activeStage, type RunView, type Stage } from './trace'
import {
  ROLES,
  type DecisionLog,
  type Mode,
  type Options,
  type Role,
  type RunRequest,
  type RunResult,
  type WorkflowInput,
} from './types'

const PROMPT_STORAGE_KEY = 'bootchicks.rolePrompts'
const LIVE_BUDGET = { round_timeout_seconds: 60, total_timeout_seconds: 150 }

type RunPhase =
  | { kind: 'idle' }
  | { kind: 'running'; log: DecisionLog | null; mode: Mode }
  | { kind: 'error'; message: string }
  | { kind: 'done'; result: RunResult; log: DecisionLog; mode: Mode; fingerprint: string }

/** `stepMs` sets the replay pace; tests pass 0 to show each run as soon as it finishes. */
export default function App({ stepMs = STEP_MS }: { stepMs?: number }) {
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
  return <Desk options={options} stepMs={stepMs} />
}

function Shell({
  onTrace,
  onSkip,
  focused,
  children,
}: {
  onTrace?: () => void
  onSkip?: () => void
  focused?: boolean
  children: ReactNode
}) {
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
          <div className="top-actions">
            {onSkip && (
              <button className="trace-btn" type="button" onClick={onSkip}>
                Skip replay
              </button>
            )}
            {onTrace && (
              <button className="trace-btn" type="button" onClick={onTrace}>
                View audit log
              </button>
            )}
          </div>
        </div>
      </header>
      <main className={focused ? 'workflow is-focused' : 'workflow'}>{children}</main>
    </div>
  )
}

function StageSection({
  stage,
  title,
  active,
  sectionRef,
  children,
}: {
  stage: Stage
  title: string
  active: boolean
  sectionRef: Ref<HTMLElement>
  children: ReactNode
}) {
  return (
    <section
      ref={sectionRef}
      className={active ? 'stage is-active' : 'stage'}
      aria-labelledby={`${stage}-stage-title`}
      aria-current={active ? 'step' : undefined}
      aria-busy={active}
    >
      <h2 className="turn-title" id={`${stage}-stage-title`}>
        {title}
      </h2>
      {children}
    </section>
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

function Desk({ options, stepMs }: { options: Options; stepMs: number }) {
  const [scenarioId, setScenarioId] = useState(options.scenarios[0].id)
  const [source, setSource] = useState<FlightSource>('synthetic')
  // The chosen real flight; starts at the verified sample until another is picked.
  const [trigger, setTrigger] = useState<WorkflowInput>(options.sample_trigger)
  const [mode, setMode] = useState<Mode>('stub')
  const [busy, setBusy] = useState<BusyPeriod[]>([])
  const [prompts, setPrompts] = useState(() => loadPrompts(options.default_prompts))
  const [phase, setPhase] = useState<RunPhase>({ kind: 'idle' })
  const [following, setFollowing] = useState(false)
  const traceRef = useRef<HTMLDivElement>(null)
  const sections = useRef<Partial<Record<Stage, HTMLElement | null>>>({})

  useEffect(() => {
    // Keep only edited prompts, so changed defaults reach users who never edited them.
    const edited = Object.fromEntries(
      ROLES.filter((r) => prompts[r] !== options.default_prompts[r]).map((r) => [r, prompts[r]]),
    )
    localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(edited))
  }, [prompts, options.default_prompts])

  const target: RunView | null = useMemo(
    () =>
      phase.kind === 'done'
        ? { log: phase.log, result: phase.result }
        : phase.kind === 'running' && phase.log
          ? { log: phase.log, result: null }
          : null,
    [phase],
  )
  const { view, replaying, skip } = usePlayback(target, stepMs)
  const working = phase.kind === 'running' || replaying
  const runMode = phase.kind === 'running' || phase.kind === 'done' ? phase.mode : mode
  const stage = working || view?.result ? activeStage(view, runMode) : null
  const stopFollowing = useCallback(() => setFollowing(false), [])
  useFollowStage(sections, stage, following, !working, stopFollowing)
  const live = (s: Stage) => working && stage === s
  const sectionRef = (s: Stage) => (el: HTMLElement | null) => {
    sections.current[s] = el
  }

  const scenario = options.scenarios.find((s) => s.id === scenarioId) ?? options.scenarios[0]
  const busyValid = Object.keys(busyPeriodErrors(busy)).length === 0
  const promptsValid = ROLES.every((role) => prompts[role].trim())
  const canRun = busyValid && (mode !== 'live' || promptsValid) && !working

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
      ...(source === 'real' ? { trigger: { ...trigger, scenario_id: scenarioId } } : {}),
    }
  }, [scenarioId, mode, busy, prompts, source, trigger, options])
  const fingerprint = JSON.stringify(request)

  async function run() {
    const requested = mode
    setPhase({ kind: 'running', log: null, mode: requested })
    setFollowing(true)
    try {
      const id = crypto.randomUUID()
      // A fresh environment per run, so earlier commits never block a new attempt.
      const { run_id } = await startRun({ ...request, environment: `ui-${id.slice(0, 12)}` }, id)
      const { result, log } = await followRun(run_id, (log) => setPhase({ kind: 'running', log, mode: requested }))
      setPhase({ kind: 'done', result, log, mode: requested, fingerprint })
    } catch (error) {
      setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
    }
  }

  function showTrace() {
    traceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    traceRef.current?.focus({ preventScroll: true })
  }

  return (
    <Shell onTrace={showTrace} onSkip={replaying ? skip : undefined} focused={working}>
      <section aria-labelledby="input-title">
        <article className="card input-card">
          <h1 id="input-title">Disruption scenario</h1>
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
            <FlightRecord source={source} trigger={trigger} onPick={setTrigger} />
            <AirportState scenario={scenario} />
          </div>
          <div className="input-columns two">
            <BusyPeriodsEditor scenario={scenario} rows={busy} onChange={setBusy} />
            <PromptEditor defaults={options.default_prompts} prompts={prompts} onChange={setPrompts} />
          </div>
          <div className="input-footer">
            <button type="button" className="primary-btn" disabled={!canRun} onClick={run}>
              {working ? 'Negotiating...' : 'Run negotiation'}
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
            <p className="note">Simulation with mock operational data. Not operational guidance.</p>
          </div>
        </article>
      </section>

      <StageSection
        stage="round1"
        title="Round 1 - Independent proposals"
        active={live('round1')}
        sectionRef={sectionRef('round1')}
      >
        <BranchConnector live={live('round1')} />
        <div className="agent-grid">
          {ROLES.map((role) => (
            <AgentCard key={role} role={role} round={1} run={view} />
          ))}
        </div>
      </StageSection>

      <StageSection
        stage="board"
        title="Proposal board"
        active={live('board')}
        sectionRef={sectionRef('board')}
      >
        <MergeConnector live={live('board')} />
        <ProposalBoard run={view} />
      </StageSection>

      <StageSection
        stage="round2"
        title="Round 2 - Votes on feasible plans"
        active={live('round2')}
        sectionRef={sectionRef('round2')}
      >
        <BranchConnector live={live('round2')} />
        <div className="agent-grid">
          {ROLES.map((role) => (
            <AgentCard key={role} role={role} round={2} run={view} />
          ))}
        </div>
      </StageSection>

      <StageSection
        stage="decision"
        title="Decision and commit"
        active={live('decision')}
        sectionRef={sectionRef('decision')}
      >
        <MergeConnector live={live('decision')} />
        <DecisionCard
          run={view}
          stale={phase.kind === 'done' && !replaying && phase.fingerprint !== fingerprint}
          traceRef={traceRef}
        />
      </StageSection>
    </Shell>
  )
}
