import {
  ROLES,
  type AgentDecision,
  type DecisionLog,
  type Mode,
  type Role,
  type RunResult,
  type TimelineEntry,
} from './types'

export type CardStatus = 'waiting' | 'running' | 'complete' | 'error' | 'skipped'

export interface LogLine {
  time: string
  message: string
}

/** A run in progress (its decisions so far) or finished (with its result). */
export interface RunView {
  log: DecisionLog
  result: RunResult | null
}

function lines(entries: TimelineEntry[]): LogLine[] {
  return entries.map((entry) => ({
    time: new Date(entry.at).toLocaleTimeString('en-GB', { hour12: false }),
    message: entry.message,
  }))
}

export function agentLog(run: RunView, round: 1 | 2, role: Role): LogLine[] {
  return lines(run.log.timeline.filter((e) => e.actor === role && e.round === round))
}

export function systemLog(run: RunView): LogLine[] {
  return lines(run.log.timeline.filter((e) => e.actor === 'SYSTEM'))
}

export function agentStatus(run: RunView | null, round: 1 | 2, role: Role): CardStatus {
  if (!run) return 'waiting'
  const agent = run.log.rounds[round]?.agents[role]
  if (!agent) return run.log.finished ? 'skipped' : 'waiting'
  return ({ DECIDING: 'running', DECIDED: 'complete', NO_REPLY: 'error' } as const)[agent.status]
}

/** Why a step never ran, once the run has finished without it. */
export function skippedReason(run: RunView): string {
  const reason = run.log.decision.fallback_reason ?? run.log.decision.terminal?.reason_text ?? ''
  return run.result?.mode === 'fallback' ? reason : `Not reached. ${reason}`
}

export function boardStatus(run: RunView | null): CardStatus {
  if (!run) return 'waiting'
  if (run.log.board) return 'complete'
  if (run.log.finished) return 'skipped'
  const round1 = run.log.rounds[1]
  return round1 && Object.values(round1.agents).every((a) => a.status === 'DECIDED') ? 'running' : 'waiting'
}

export type Stage = 'round1' | 'board' | 'round2' | 'decision'

/** The stage a run is working on, or showing as its result once finished. */
export function activeStage(run: RunView | null, mode: Mode): Stage {
  if (run?.result) return 'decision'
  const round2 = run?.log.rounds[2]
  if (round2) return Object.values(round2.agents).some((a) => a.status === 'DECIDING') ? 'round2' : 'decision'
  if (run && boardStatus(run) !== 'waiting') return 'board'
  return mode === 'fallback' ? 'decision' : 'round1'
}

/** A point in the run to pause on during a replay; `steps` is how long the previous point stays shown. */
export interface Keyframe {
  sequence: number
  steps: number
}

const REPLY_KINDS = new Set(['AGENT_MESSAGE', 'AGENT_ABSENT'])

/**
 * The visible steps of a run in order: each round starting, each agent replying, the proposal board, and
 * the finished result. Agents replying one after another get a short pause; stage changes a longer one.
 */
export function keyframes(run: RunView): Keyframe[] {
  const frames: Keyframe[] = []
  let previousReply = false
  for (const entry of run.log.timeline) {
    const reply = entry.actor !== 'SYSTEM' && REPLY_KINDS.has(entry.kind)
    if (!reply && entry.kind !== 'ROUND_INPUT' && entry.kind !== 'PROPOSAL_BOARD') continue
    if (frames.at(-1)?.sequence === entry.sequence) continue
    frames.push({ sequence: entry.sequence, steps: reply && previousReply ? 1 : 2 })
    previousReply = reply
  }
  if (run.result) frames.push({ sequence: Infinity, steps: 2 })
  return frames
}

function replied(timeline: TimelineEntry[], role: Role, round: number) {
  return timeline.some((e) => e.actor === role && e.round === round && REPLY_KINDS.has(e.kind))
}

/** The run as it looked once its timeline reached `sequence`; `Infinity` is the run itself. */
export function runAt(run: RunView, sequence: number): RunView {
  if (sequence === Infinity) return run
  const timeline = run.log.timeline.filter((e) => e.sequence <= sequence)
  const rounds: DecisionLog['rounds'] = {}
  for (const key of ['1', '2'] as const) {
    const round = run.log.rounds[key]
    const number = Number(key)
    if (!round || !timeline.some((e) => e.kind === 'ROUND_INPUT' && e.round === number)) continue
    const agents = Object.fromEntries(
      ROLES.map((role): [Role, AgentDecision] => {
        const agent = round.agents[role]
        if (replied(timeline, role, number)) return [role, agent]
        const pending = { status: 'DECIDING', decided_at: null, provider: null, model: null, absent_reason: null } as const
        return [role, { ...agent, ...pending, proposals: [], votes: [] }]
      }),
    ) as Record<Role, AgentDecision>
    rounds[key] = { ...round, agents }
  }
  const board = timeline.some((e) => e.kind === 'PROPOSAL_BOARD') ? run.log.board : null
  return { result: null, log: { ...run.log, status: 'RUNNING', finished: false, timeline, rounds, board } }
}
