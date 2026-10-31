import { useId, useState } from 'react'
import { busyPeriodErrors, type BusyPeriod } from '../busyPeriods'
import { formatNumber, ROLE_NAMES } from '../labels'
import { ROLES, type Mode, type Options, type Role, type ScenarioAirport, type ScenarioOption } from '../types'

export type FlightSource = 'synthetic' | 'sample'

const MODES: { mode: Mode; label: string; hint: string }[] = [
  { mode: 'stub', label: 'Fixture agents', hint: 'Deterministic scripted roles. No API calls.' },
  { mode: 'live', label: 'Claude agents', hint: 'Three independent Claude calls per round.' },
  { mode: 'fallback', label: 'No agents', hint: 'Skip negotiation; deterministic planner only.' },
]

export function ScenarioControls({
  options,
  scenarioId,
  source,
  mode,
  onScenario,
  onSource,
  onMode,
}: {
  options: Options
  scenarioId: string
  source: FlightSource
  mode: Mode
  onScenario: (id: string) => void
  onSource: (source: FlightSource) => void
  onMode: (mode: Mode) => void
}) {
  const scenario = options.scenarios.find((s) => s.id === scenarioId)
  const row = options.sample_trigger.flight_row
  return (
    <div className="input-column">
      <h2>Scenario controls</h2>
      <div className="field">
        <label htmlFor="scenario">Scenario</label>
        <select id="scenario" value={scenarioId} onChange={(e) => onScenario(e.target.value)}>
          {options.scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <p className="field-hint">{scenario?.description}</p>
      </div>
      <div className="field">
        <label htmlFor="flight">Flight</label>
        <select id="flight" value={source} onChange={(e) => onSource(e.target.value as FlightSource)}>
          <option value="synthetic">Synthetic demo flight</option>
          <option value="sample">
            {row.AIRLINE} {row.FLIGHT_NUMBER}, {row.ORIGIN_AIRPORT} to {row.DESTINATION_AIRPORT}
          </option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="mode">Agents</label>
        <select id="mode" value={mode} onChange={(e) => onMode(e.target.value as Mode)}>
          {MODES.map((m) => (
            <option key={m.mode} value={m.mode} disabled={m.mode === 'live' && !options.live_available}>
              {m.label}
              {m.mode === 'live' && !options.live_available ? ' (needs an API key)' : ''}
            </option>
          ))}
        </select>
        <p className="field-hint">
          {MODES.find((m) => m.mode === mode)?.hint}
          {mode === 'live' && ` Model: ${options.model}.`}
        </p>
        {!options.live_available && (
          <p className="field-hint">
            Set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> to enable Claude agents.
          </p>
        )}
      </div>
    </div>
  )
}

function Fields({ fields }: { fields: [label: string, value: string][] }) {
  return (
    <dl className="input-fields">
      {fields.map(([label, value]) => (
        <div className="field" key={label}>
          <dt className="field-label">{label}</dt>
          <dd className="field-value">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** HHMM as stored in the DOT data, e.g. 1228 to "12:28". */
function hhmm(value: number): string {
  const text = String(value).padStart(4, '0')
  return `${text.slice(0, 2)}:${text.slice(2)}`
}

export function FlightRecord({ options, source }: { options: Options; source: FlightSource }) {
  const trigger = options.sample_trigger
  const row = trigger.flight_row
  if (source === 'synthetic') {
    return (
      <div className="input-column">
        <h2>Flight record</h2>
        <div className="source-row">
          <span className="source-badge sim-badge">Synthetic fixture</span>
        </div>
        <Fields
          fields={[
            ['Flight', 'SYNTHETIC-DEMO'],
            ['Destination', 'DFW'],
          ]}
        />
      </div>
    )
  }
  const date = `${row.YEAR}-${String(row.MONTH).padStart(2, '0')}-${String(row.DAY).padStart(2, '0')}`
  return (
    <div className="input-column">
      <h2>Flight record</h2>
      <div className="source-row">
        <span className="source-badge">US DOT dataset</span>
        <span className="source-badge">CSV line {trigger.provenance.csv_line}</span>
      </div>
      <Fields
        fields={[
          ['Flight', `${row.AIRLINE} ${row.FLIGHT_NUMBER}`],
          ['Airline', trigger.airline_row.AIRLINE],
          ['Route', `${row.ORIGIN_AIRPORT} to ${row.DESTINATION_AIRPORT}`],
          ['Date', date],
          ['Scheduled arrival', hhmm(row.SCHEDULED_ARRIVAL)],
          ['Arrival delay', row.ARRIVAL_DELAY === null ? 'Not recorded' : `${formatNumber(row.ARRIVAL_DELAY)} min`],
        ]}
      />
    </div>
  )
}

function runwayText(airport: ScenarioAirport, windowMin: number): string {
  return airport.runways
    .map((runway) => {
      if (runway.closed.length === 0) return `${runway.id} open`
      if (runway.closed.some((w) => w.start_min <= 0 && w.end_min >= windowMin)) return `${runway.id} closed`
      const windows = runway.closed.map((w) =>
        w.start_min <= 0 ? `until +${w.end_min} min` : `+${w.start_min} to +${w.end_min} min`,
      )
      return `${runway.id} closed ${windows.join(', ')}`
    })
    .join(' · ')
}

export function AirportState({ scenario }: { scenario: ScenarioOption }) {
  const a = scenario.aircraft
  const destination = scenario.airports.find((airport) => airport.kind === 'destination')!
  const alternate = scenario.airports.find((airport) => airport.kind === 'alternate')
  return (
    <div className="input-column">
      <h2>Simulated airport state</h2>
      <div className="source-row">
        <span className="source-badge sim-badge">Simulated inputs</span>
        <span className="source-badge sim-badge">Mock profiles</span>
      </div>
      <Fields
        fields={[
          ['Aircraft', a.type_label],
          [
            'Fuel on board',
            `${formatNumber(a.fuel_kg)} kg (landing floor ${formatNumber(a.protected_landing_kg)} kg)`,
          ],
          [`${destination.iata_code} runways`, runwayText(destination, scenario.window_min)],
          ...(alternate
            ? [[`${alternate.iata_code} runways (alternate)`, runwayText(alternate, scenario.window_min)] as [string, string]]
            : []),
          [`${destination.iata_code} gates`, `${destination.gates.join(', ')} (assigned ${scenario.preferred_gate})`],
          [`${destination.iata_code} crews`, String(destination.crews)],
        ]}
      />
    </div>
  )
}

export function BusyPeriodsEditor({
  scenario,
  rows,
  onChange,
}: {
  scenario: ScenarioOption
  rows: BusyPeriod[]
  onChange: (rows: BusyPeriod[]) => void
}) {
  const errors = busyPeriodErrors(rows)
  const gatesFor = (airport: string) => scenario.airports.find((a) => a.iata_code === airport)?.gates ?? []
  const update = (id: string, change: Partial<BusyPeriod>) =>
    onChange(rows.map((row) => (row.id === id ? { ...row, ...change } : row)))
  const add = () => {
    const airport = scenario.airports[0]
    onChange([
      ...rows,
      {
        id: crypto.randomUUID(),
        airport: airport.iata_code,
        gate_id: scenario.preferred_gate,
        start_min: 0,
        end_min: 30,
      },
    ])
  }
  return (
    <fieldset className="input-column">
      <legend className="section-title">Gate busy periods</legend>
      <p className="field-hint">Minutes after the scenario starts.</p>
      {rows.length > 0 && (
        <div className="busy-table" role="table" aria-label="Gate busy periods">
          <div className="busy-row busy-head" role="row">
            <span role="columnheader">Airport</span>
            <span role="columnheader">Gate</span>
            <span role="columnheader">From</span>
            <span role="columnheader">Until</span>
            <span />
          </div>
          {rows.map((row, index) => (
            <div key={row.id} role="row">
              <div className="busy-row">
                <select
                  aria-label={`Period ${index + 1} airport`}
                  value={row.airport}
                  onChange={(e) => {
                    const gates = gatesFor(e.target.value)
                    update(row.id, {
                      airport: e.target.value,
                      gate_id: gates.includes(row.gate_id) ? row.gate_id : gates[0],
                    })
                  }}
                >
                  {scenario.airports.map((a) => (
                    <option key={a.iata_code} value={a.iata_code}>
                      {a.iata_code}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={`Period ${index + 1} gate`}
                  value={row.gate_id}
                  onChange={(e) => update(row.id, { gate_id: e.target.value })}
                >
                  {gatesFor(row.airport).map((gate) => (
                    <option key={gate}>{gate}</option>
                  ))}
                </select>
                <MinuteInput
                  label={`Period ${index + 1} from`}
                  value={row.start_min}
                  invalid={Boolean(errors[row.id])}
                  onChange={(start_min) => update(row.id, { start_min })}
                />
                <MinuteInput
                  label={`Period ${index + 1} until`}
                  value={row.end_min}
                  invalid={Boolean(errors[row.id])}
                  onChange={(end_min) => update(row.id, { end_min })}
                />
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Remove period ${index + 1}`}
                  onClick={() => onChange(rows.filter((r) => r.id !== row.id))}
                >
                  ×
                </button>
              </div>
              {errors[row.id] && (
                <p className="field-error" role="alert">
                  Period {index + 1}: {errors[row.id]}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      <button type="button" className="secondary-button" onClick={add}>
        Add busy period
      </button>
    </fieldset>
  )
}

function MinuteInput({
  label,
  value,
  invalid,
  onChange,
}: {
  label: string
  value: number
  invalid: boolean
  onChange: (value: number) => void
}) {
  return (
    <input
      type="number"
      inputMode="numeric"
      min={0}
      step={1}
      aria-label={label}
      aria-invalid={invalid}
      value={Number.isNaN(value) ? '' : value}
      onChange={(e) => onChange(e.target.value === '' ? Number.NaN : Number(e.target.value))}
    />
  )
}

export function PromptEditor({
  defaults,
  prompts,
  onChange,
}: {
  defaults: Record<Role, string>
  prompts: Record<Role, string>
  onChange: (prompts: Record<Role, string>) => void
}) {
  const [active, setActive] = useState<Role>('ATC')
  const id = useId()
  const edited = ROLES.filter((role) => prompts[role] !== defaults[role])
  const blank = !prompts[active].trim()
  return (
    <details className="input-column prompts">
      <summary className="section-title">
        Agent system prompts
        {edited.length > 0 && (
          <span className="count-badge">{edited.length} edited</span>
        )}
      </summary>
      <div className="tabs" role="tablist" aria-label="Agent role">
        {ROLES.map((role) => (
          <button
            key={role}
            type="button"
            role="tab"
            id={`${id}-${role}`}
            aria-selected={active === role}
            aria-controls={`${id}-panel`}
            className="tab"
            onClick={() => setActive(role)}
          >
            {ROLE_NAMES[role]}
            {prompts[role] !== defaults[role] && <span className="edited-dot" aria-label="edited" />}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${active}`}>
        <textarea
          aria-label={`${ROLE_NAMES[active]} system prompt`}
          aria-invalid={blank}
          value={prompts[active]}
          rows={14}
          maxLength={8000}
          onChange={(e) => onChange({ ...prompts, [active]: e.target.value })}
        />
        {blank && (
          <p className="field-error" role="alert">
            The {ROLE_NAMES[active]} prompt is empty. Enter instructions or reset it.
          </p>
        )}
        <div className="prompt-actions">
          <span className="field-hint">
            {prompts[active] === defaults[active] ? 'Default prompt' : 'Edited, saved in this browser'}
          </span>
          <button
            type="button"
            className="secondary-button"
            disabled={prompts[active] === defaults[active]}
            onClick={() => onChange({ ...prompts, [active]: defaults[active] })}
          >
            Reset to default
          </button>
        </div>
      </div>
    </details>
  )
}
