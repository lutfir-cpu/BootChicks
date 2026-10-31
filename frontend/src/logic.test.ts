import { describe, expect, it } from 'vitest'
import { busyPeriodErrors, type BusyPeriod } from './busyPeriods'
import { clockTime, formatCheckValue, improvements, minutesAfter } from './labels'
import consensus from './test/fixtures/consensus.json'
import escalated from './test/fixtures/escalated.json'
import fallback from './test/fixtures/fallback.json'
import {
  activeStage,
  agentLog,
  agentStatus,
  boardStatus,
  keyframes,
  runAt,
  skippedReason,
  systemLog,
  type RunView,
} from './trace'
import type { DecisionLog, RunResult } from './types'

const period = (id: string, gate: string, start: number, end: number, airport = 'DFW'): BusyPeriod => ({
  id,
  airport,
  gate_id: gate,
  start_min: start,
  end_min: end,
})

describe('busyPeriodErrors', () => {
  it('accepts half-open periods that only touch', () => {
    expect(busyPeriodErrors([period('a', 'A1', 0, 30), period('b', 'A1', 30, 60)])).toEqual({})
  })

  it('flags backwards, empty and fractional periods', () => {
    expect(
      busyPeriodErrors([period('a', 'A1', 30, 30), period('b', 'B2', 40, 10), period('c', 'C3', 0.5, 10)]),
    ).toEqual({
      a: 'End must be after the start.',
      b: 'End must be after the start.',
      c: 'Use whole minutes.',
    })
  })

  it('flags overlaps on the same gate only', () => {
    const errors = busyPeriodErrors([
      period('a', 'A1', 0, 30),
      period('b', 'A1', 20, 40),
      period('c', 'B2', 20, 40),
      period('d', 'A1', 20, 40, 'DAL'),
    ])
    expect(Object.keys(errors).sort()).toEqual(['a', 'b'])
    expect(errors.a).toBe('Overlaps another period on DFW A1.')
  })
})

describe('labels', () => {
  it('describes gains and losses against the baseline', () => {
    expect(
      improvements({ holding_saved_min: 10, earlier_gate_arrival_min: -5, overtime_saved_min: 0 }),
    ).toEqual([
      { label: 'Holding', text: '10 min less', tone: 'better' },
      { label: 'Gate arrival', text: '5 min later', tone: 'worse' },
      { label: 'Crew overtime', text: 'same as baseline', tone: 'same' },
    ])
  })

  it('formats scenario times', () => {
    expect(clockTime('2026-10-31T06:25:00Z')).toBe('06:25')
    expect(minutesAfter('2026-10-31T06:25:00Z', '2026-10-31T06:00:00Z')).toBe('+25 min')
  })

  it('formats check values in readable units', () => {
    expect(formatCheckValue(2700, 'seconds')).toBe('45 min')
    expect(formatCheckValue(2520, 'UTC')).toBe('42 min')
    expect(formatCheckValue('2026-10-31T06:33:00+00:00', 'UTC')).toBe('06:33')
    expect(formatCheckValue('entire occupancy including buffer', 'UTC')).toBe('entire occupancy including buffer')
    expect(formatCheckValue('93e03d68411b826a6fa9', 'sha256')).toBe('93e03d68411b')
    expect(formatCheckValue(4600, 'kg')).toBe('4,600 kg')
    expect(formatCheckValue(true, 'boolean')).toBe('yes')
  })
})

const finished = (fixture: { result: unknown; decisions: unknown }): RunView => ({
  log: fixture.decisions as DecisionLog,
  result: fixture.result as RunResult,
})

describe('trace', () => {
  it('marks every agent complete and splits the log by role and round', () => {
    const run = finished(consensus)
    expect(agentStatus(run, 1, 'ATC')).toBe('complete')
    expect(agentStatus(run, 2, 'GROUND')).toBe('complete')
    expect(boardStatus(run)).toBe('complete')
    expect(agentLog(run, 2, 'PILOT')[1].message).toMatch(/^Voted on 3 plans/)
    expect(agentLog(run, 1, 'PILOT').every((line) => !line.message.startsWith('Voted'))).toBe(true)
    expect(systemLog(run).at(-1)?.message).toMatch(/^Run finished: Consensus/)
  })

  it('skips round 2 after an escalation and says why', () => {
    const run = finished(escalated)
    expect(agentStatus(run, 1, 'ATC')).toBe('complete')
    expect(agentStatus(run, 2, 'ATC')).toBe('skipped')
    expect(skippedReason(run)).toBe('Not reached. None of the proposed plans passed every hard check.')
  })

  it('skips every agent step when the run used no agents', () => {
    const run = finished(fallback)
    expect(agentStatus(run, 1, 'GROUND')).toBe('skipped')
    expect(boardStatus(run)).toBe('skipped')
    expect(skippedReason(run)).toBe('Agents were skipped; the deterministic planner chose directly.')
  })

  it('shows agents deciding while a round is in progress', () => {
    const log = structuredClone(consensus.decisions) as DecisionLog
    log.finished = false
    log.board = null
    delete log.rounds[2]
    log.rounds[1]!.agents.PILOT.status = 'DECIDING'
    const run: RunView = { log, result: null }
    expect(agentStatus(run, 1, 'PILOT')).toBe('running')
    expect(agentStatus(run, 2, 'PILOT')).toBe('waiting')
    expect(boardStatus(run)).toBe('waiting')
    expect(agentStatus(null, 1, 'ATC')).toBe('waiting')
  })
})

describe('replay', () => {
  it('pauses on each round, agent reply and board, then the result', () => {
    expect(keyframes(finished(consensus))).toEqual(
      [3, 4, 5, 6, 7, 8, 9, 10, 11, Infinity].map((sequence, i) => ({
        sequence,
        steps: [2, 2, 1, 1, 2, 2, 2, 1, 1, 2][i],
      })),
    )
    expect(keyframes(finished(escalated)).map((f) => f.sequence)).toEqual([3, 4, 5, 6, 7, Infinity])
    expect(keyframes(finished(fallback))).toEqual([{ sequence: Infinity, steps: 2 }])
    expect(keyframes({ log: finished(consensus).log, result: null }).at(-1)?.sequence).toBe(11)
  })

  it('rebuilds the run as it looked at each step', () => {
    const run = finished(consensus)
    const drafting = runAt(run, 4)
    expect(drafting.result).toBeNull()
    expect(drafting.log.finished).toBe(false)
    expect(agentStatus(drafting, 1, 'ATC')).toBe('complete')
    expect(agentStatus(drafting, 1, 'PILOT')).toBe('running')
    expect(drafting.log.rounds[1]!.agents.PILOT.proposals).toEqual([])
    expect(agentStatus(drafting, 2, 'PILOT')).toBe('waiting')
    expect(boardStatus(drafting)).toBe('waiting')
    expect(systemLog(drafting).map((l) => l.message)).toHaveLength(2)

    expect(boardStatus(runAt(run, 6))).toBe('running')
    expect(boardStatus(runAt(run, 7))).toBe('complete')
    expect(agentStatus(runAt(run, 8), 2, 'GROUND')).toBe('running')
    expect(runAt(run, Infinity)).toBe(run)
  })

  it('names the stage in focus', () => {
    const run = finished(consensus)
    expect(activeStage(null, 'stub')).toBe('round1')
    expect(activeStage(null, 'fallback')).toBe('decision')
    expect(activeStage(runAt(run, 5), 'stub')).toBe('round1')
    expect(activeStage(runAt(run, 6), 'stub')).toBe('board')
    expect(activeStage(runAt(run, 7), 'stub')).toBe('board')
    expect(activeStage(runAt(run, 8), 'stub')).toBe('round2')
    expect(activeStage(runAt(run, 10), 'stub')).toBe('round2')
    expect(activeStage(runAt(run, 11), 'stub')).toBe('decision')
    expect(activeStage(run, 'stub')).toBe('decision')
  })
})
