import { describe, expect, it } from 'vitest'
import { busyPeriodErrors, type BusyPeriod } from './busyPeriods'
import { clockTime, formatCheckValue, improvements, minutesAfter, reasonText } from './labels'
import { readNegotiation, runwayOf } from './negotiation'
import consensus from './test/fixtures/consensus.json'
import escalated from './test/fixtures/escalated.json'
import type { AuditEvent, RunResult } from './types'

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
    expect(reasonText('NO_UNANIMOUS_PLAN')).toBe('No feasible plan was accepted by all three roles.')
    expect(reasonText('SOMETHING_NEW')).toBe('something new')
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

describe('readNegotiation', () => {
  it('rebuilds both rounds, the board and the commit of a consensus run', () => {
    const result = consensus.result as unknown as RunResult
    const view = readNegotiation(consensus.events as unknown as AuditEvent[])
    expect(view.clock).toBe('2026-10-31T06:00:00Z')
    expect(Object.keys(view.rounds[1] ?? {})).toEqual(['ATC', 'PILOT', 'GROUND'])
    expect(view.rounds[1]?.GROUND?.proposals.length).toBeGreaterThan(0)
    expect(view.rounds[2]?.ATC?.votes.length).toBe(view.board?.filter((e) => e.feasible).length)
    expect(view.selectedHash).toBe(result.selected_plan?.plan_hash)
    expect(view.unanimous).toContain(result.selected_plan?.candidate_id)
    expect(view.commit?.snapshotAfter).toMatch(/:v2$/)
    const action = result.selected_plan!.action
    expect(runwayOf(view, action.airport, action.taxi_path_id)).toBe('R1')
  })

  it('records the fallback and rejected plans of an escalated run', () => {
    const view = readNegotiation(escalated.events as unknown as AuditEvent[])
    expect(view.rounds[2]).toBeUndefined()
    expect(view.fallbackStarted).toBe('NO_FEASIBLE_PROPOSALS')
    expect(view.rejections.length).toBeGreaterThan(0)
    expect(view.commit).toBeNull()
  })
})
