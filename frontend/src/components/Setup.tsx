import { useId, useState } from 'react'
import { busyPeriodErrors, type BusyPeriod } from '../busyPeriods'
import { ROLE_FOCUS, ROLE_NAMES } from '../labels'
import { ROLES, type Mode, type Options, type Role, type ScenarioOption } from '../types'

export type FlightSource = 'synthetic' | 'sample'

export function ScenarioPicker({
  scenarios,
  value,
  onChange,
}: {
  scenarios: ScenarioOption[]
  value: string
  onChange: (id: string) => void
}) {
  return (
    <fieldset className="section">
      <legend className="section-title">Scenario</legend>
      <div className="choice-list">
        {scenarios.map((scenario) => (
          <label key={scenario.id} className="choice">
            <input
              type="radio"
              name="scenario"
              value={scenario.id}
              checked={value === scenario.id}
              onChange={() => onChange(scenario.id)}
            />
            <span>
              <span className="choice-label">{scenario.label}</span>
              <span className="choice-hint">{scenario.description}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function FlightSourcePicker({
  options,
  value,
  onChange,
}: {
  options: Options
  value: FlightSource
  onChange: (source: FlightSource) => void
}) {
  const row = options.sample_trigger.flight_row
  const date = `${row.YEAR}-${String(row.MONTH).padStart(2, '0')}-${String(row.DAY).padStart(2, '0')}`
  return (
    <fieldset className="section">
      <legend className="section-title">Flight</legend>
      <div className="choice-list">
        <label className="choice">
          <input
            type="radio"
            name="source"
            checked={value === 'synthetic'}
            onChange={() => onChange('synthetic')}
          />
          <span>
            <span className="choice-label">Synthetic demo flight</span>
            <span className="choice-hint">Fixture arrival into DFW.</span>
          </span>
        </label>
        <label className="choice">
          <input
            type="radio"
            name="source"
            checked={value === 'sample'}
            onChange={() => onChange('sample')}
          />
          <span>
            <span className="choice-label">
              {row.AIRLINE} {row.FLIGHT_NUMBER}, {row.ORIGIN_AIRPORT} to {row.DESTINATION_AIRPORT}
            </span>
            <span className="choice-hint">
              Real US DOT record from {date} (CSV line {options.sample_trigger.provenance.csv_line}). Only
              the trigger and delay are real; airport resources stay synthetic.
            </span>
          </span>
        </label>
      </div>
    </fieldset>
  )
}

const MODES: { mode: Mode; label: string; hint: string }[] = [
  { mode: 'stub', label: 'Fixture agents', hint: 'Deterministic scripted roles. No API calls.' },
  { mode: 'live', label: 'Claude agents', hint: 'Three independent Claude calls per round.' },
  { mode: 'fallback', label: 'No agents', hint: 'Skip negotiation; deterministic planner only.' },
]

export function ModePicker({
  options,
  value,
  onChange,
}: {
  options: Options
  value: Mode
  onChange: (mode: Mode) => void
}) {
  return (
    <fieldset className="section">
      <legend className="section-title">Agents</legend>
      <div className="segmented" role="radiogroup" aria-label="Agents">
        {MODES.map(({ mode, label }) => {
          const disabled = mode === 'live' && !options.live_available
          return (
            <label key={mode} className={disabled ? 'segment disabled' : 'segment'}>
              <input
                type="radio"
                name="mode"
                value={mode}
                checked={value === mode}
                disabled={disabled}
                onChange={() => onChange(mode)}
              />
              <span>{label}</span>
            </label>
          )
        })}
      </div>
      <p className="hint">
        {MODES.find((m) => m.mode === value)?.hint}
        {value === 'live' && ` Model: ${options.model}.`}
      </p>
      {!options.live_available && (
        <p className="hint">
          Claude agents need <code>ANTHROPIC_API_KEY</code> in the repository's <code>.env</code>; restart the
          server after setting it.
        </p>
      )}
    </fieldset>
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
    <fieldset className="section">
      <legend className="section-title">Gate busy periods</legend>
      <p className="hint">
        Block a gate for other traffic, in minutes after the scenario starts. A period ending at 30 frees the gate
        at minute 30.
      </p>
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
  mode,
  onChange,
}: {
  defaults: Record<Role, string>
  prompts: Record<Role, string>
  mode: Mode
  onChange: (prompts: Record<Role, string>) => void
}) {
  const [active, setActive] = useState<Role>('ATC')
  const id = useId()
  const edited = ROLES.filter((role) => prompts[role] !== defaults[role])
  const blank = !prompts[active].trim()
  return (
    <details className="section prompts">
      <summary className="section-title">
        Agent system prompts
        {edited.length > 0 && (
          <span className="badge">{edited.length} edited</span>
        )}
      </summary>
      <p className="hint">
        {mode === 'live'
          ? 'Each Claude role receives its own system prompt. Python still enforces every hard check.'
          : 'Used only by Claude agents; the current agent mode ignores them.'}
      </p>
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
        <p className="hint">{ROLE_FOCUS[active]}</p>
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
          <span className="hint">
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
