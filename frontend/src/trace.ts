import type { DecisionLog, Role, RunResult, TimelineEntry } from './types'

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
