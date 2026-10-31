import type { GateOccupancy } from './types'

export interface BusyPeriod extends GateOccupancy {
  id: string
}

/**
 * Mirror the backend's checks so problems show next to the row before submitting.
 * Intervals are half-open, so a period ending at 30 and one starting at 30 do not overlap.
 */
export function busyPeriodErrors(rows: BusyPeriod[]): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const row of rows) {
    if (!Number.isInteger(row.start_min) || !Number.isInteger(row.end_min)) {
      errors[row.id] = 'Use whole minutes.'
    } else if (row.start_min < 0) {
      errors[row.id] = 'Start cannot be negative.'
    } else if (row.end_min <= row.start_min) {
      errors[row.id] = 'End must be after the start.'
    }
  }
  const valid = rows.filter((row) => !errors[row.id])
  for (const row of valid) {
    const clash = valid.find(
      (other) =>
        other !== row &&
        other.airport === row.airport &&
        other.gate_id === row.gate_id &&
        other.start_min < row.end_min &&
        row.start_min < other.end_min,
    )
    if (clash) errors[row.id] = `Overlaps another period on ${row.airport} ${row.gate_id}.`
  }
  return errors
}

export function toOccupancies(rows: BusyPeriod[]): GateOccupancy[] {
  return rows.map(({ airport, gate_id, start_min, end_min }) => ({
    airport,
    gate_id,
    start_min,
    end_min,
  }))
}
