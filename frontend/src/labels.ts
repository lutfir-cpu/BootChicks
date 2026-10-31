import type { PlannedAction, Role, RunStatus } from './types'

export const ROLE_NAMES: Record<Role, string> = {
  ATC: 'ATC',
  PILOT: 'Pilot',
  GROUND: 'Ground',
}

export const STATUS_TEXT: Record<RunStatus, { title: string; summary: string }> = {
  CONSENSUS: {
    title: 'Consensus',
    summary: 'All three roles accepted the same validated plan, and its resources were committed.',
  },
  FALLBACK: {
    title: 'Fallback plan',
    summary: 'The roles did not agree, so deterministic code chose a plan that passes every hard check. This is not agent consensus.',
  },
  ESCALATED: {
    title: 'Escalated',
    summary: 'No plan passed every hard check. A human must decide; nothing was booked.',
  },
  FAILED: {
    title: 'Run failed',
    summary: 'The run stopped before reaching a decision. Nothing was booked.',
  },
}

export const MODE_NAMES: Record<string, string> = {
  stub: 'Fixture agents',
  live: 'Claude agents',
  fallback: 'No agents',
  recorded_replay: 'Recorded replay',
}

/** Clock time in UTC, e.g. "06:25". Scenario times are synthetic, so the date is omitted. */
export function clockTime(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16)
}

/** A plan in one line, e.g. "06:25 · R1 · gate B2". */
export function actionText(action: PlannedAction): string {
  return `${clockTime(action.landing_slot)} · ${action.runway_id ?? action.airport} · gate ${action.gate_id}`
}

/** Minutes after the scenario clock, e.g. "+25 min". */
export function minutesAfter(iso: string, clock: string | null): string {
  if (!clock) return ''
  const minutes = Math.round((Date.parse(iso) - Date.parse(clock)) / 60000)
  return `${minutes >= 0 ? '+' : ''}${minutes} min`
}

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** Render a check's measured value, limit or margin in operator-friendly units. */
export function formatCheckValue(value: number | string | boolean | null, unit: string): string {
  if (value === null) return '-'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'string') {
    if (unit === 'UTC' && !Number.isNaN(Date.parse(value)) && value.includes('T')) return clockTime(value)
    if (unit === 'sha256') return value.slice(0, 12)
    return value
  }
  // Durations are stored in seconds; minutes read better next to the rest of the plan.
  const [amount, label] = unit === 'seconds' || unit === 'UTC' ? [value / 60, 'min'] : [value, unit]
  const text = Number.isInteger(amount) ? formatNumber(amount) : formatNumber(amount, 1)
  return unit === 'boolean' ? text : `${text} ${label}`
}

const IMPROVEMENTS: [key: string, label: string, unit: string, better: string, worse: string][] = [
  ['holding_saved_min', 'Holding', 'min', 'less', 'more'],
  ['airborne_fuel_saved_kg', 'Airborne fuel', 'kg', 'less', 'more'],
  ['earlier_gate_arrival_min', 'Gate arrival', 'min', 'earlier', 'later'],
  ['overtime_saved_min', 'Crew overtime', 'min', 'less', 'more'],
  ['connections_saved', 'Missed connections', 'passengers', 'fewer', 'more'],
]

export interface Improvement {
  label: string
  text: string
  tone: 'better' | 'worse' | 'same'
}

/** Compare the chosen plan with the baseline; positive metric values favour the chosen plan. */
export function improvements(metrics: Record<string, number>): Improvement[] {
  return IMPROVEMENTS.filter(([key]) => key in metrics).map(([key, label, unit, better, worse]) => {
    const value = metrics[key]
    if (value === 0) return { label, text: 'same as baseline', tone: 'same' }
    return {
      label,
      text: `${formatNumber(Math.abs(value))} ${unit} ${value > 0 ? better : worse}`,
      tone: value > 0 ? 'better' : 'worse',
    }
  })
}
