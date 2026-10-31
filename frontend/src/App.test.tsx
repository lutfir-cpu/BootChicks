import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import consensus from './test/fixtures/consensus.json'
import escalated from './test/fixtures/escalated.json'
import fallback from './test/fixtures/fallback.json'
import optionsFixture from './test/fixtures/options.json'
import type { FlightSummary, Options, RunRequest, WorkflowInput } from './types'

interface Server {
  options: Options
  fixture: { result: unknown; decisions: unknown }
  submitted: { body: RunRequest; key: string }[]
  /** Imported real flights, keyed by CSV line; null until imported. */
  flights: Record<number, WorkflowInput> | null
}

function summary(trigger: WorkflowInput): FlightSummary {
  const f = trigger.flight_row
  return {
    csv_line: trigger.provenance.csv_line!,
    date: `${f.YEAR}-0${f.MONTH}-0${f.DAY}`,
    airline: f.AIRLINE,
    airline_name: trigger.airline_row.AIRLINE,
    flight_number: String(f.FLIGHT_NUMBER),
    origin: f.ORIGIN_AIRPORT,
    destination: f.DESTINATION_AIRPORT,
    scheduled_arrival: f.SCHEDULED_ARRIVAL,
    delay_min: f.ARRIVAL_DELAY ?? 0,
  }
}

/** A second imported flight: the sample, flown from Austin on 3 July. */
function austinFlight(sample: WorkflowInput): WorkflowInput {
  return {
    ...sample,
    flight_row: { ...sample.flight_row, FLIGHT_NUMBER: '1356', ORIGIN_AIRPORT: 'AUS', MONTH: 7, DAY: 3 },
    provenance: { ...sample.provenance, csv_line: 2928819 },
  }
}

let server: Server

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

beforeEach(() => {
  const options = structuredClone(optionsFixture) as Options
  const austin = austinFlight(options.sample_trigger)
  server = {
    options,
    fixture: consensus,
    submitted: [],
    flights: { 3121: options.sample_trigger, 2928819: austin },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/options') return json(server.options)
      if (url.startsWith('/flights?')) {
        if (!server.flights) return json({ imported: null, matches: 0, flights: [] })
        const words = (new URLSearchParams(url.split('?')[1]).get('q') ?? '').toLowerCase().split(/\s+/).filter(Boolean)
        const flights = Object.values(server.flights)
          .map(summary)
          .filter((f) => words.every((w) => `${f.airline} ${f.flight_number} ${f.origin} ${f.date}`.toLowerCase().includes(w)))
        return json({ imported: { rows: 5819079, disrupted: 376125, supported: 17310 }, matches: flights.length, flights })
      }
      const flight = url.match(/^\/flights\/(\d+)$/)
      if (flight) return json(server.flights?.[Number(flight[1])] ?? { detail: 'Flight not imported' }, server.flights?.[Number(flight[1])] ? 200 : 404)
      if (url === '/runs' && init?.method === 'POST') {
        const key = (init.headers as Record<string, string>)['Idempotency-Key']
        server.submitted.push({ body: JSON.parse(init.body as string), key })
        return json({ run_id: 'run-1' }, 202)
      }
      if (url === '/runs/run-1') {
        const result = server.fixture.result as { status: string }
        return json({ run_id: 'run-1', status: result.status, result })
      }
      if (url === '/runs/run-1/decisions') return json(server.fixture.decisions)
      return json({ detail: 'Not found' }, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function renderDesk(stepMs = 0) {
  const user = userEvent.setup()
  render(<App stepMs={stepMs} />)
  await screen.findByRole('button', { name: 'Run negotiation' })
  return user
}

function stage(name: string) {
  return screen.getByRole('region', { name })
}

const STAGES = [
  'Round 1 - Proposals',
  'Hard checks',
  'Round 2 - Votes',
  'Decision',
]

function currentStage() {
  return STAGES.find((name) => stage(name).getAttribute('aria-current') === 'step') ?? null
}

function scrolledTo() {
  return vi.mocked(Element.prototype.scrollIntoView).mock.contexts.map((el) =>
    (el as HTMLElement).getAttribute('aria-labelledby'),
  )
}

function outcome() {
  return within(screen.getByRole('article', { name: 'Outcome' }))
}

async function runAndWait(user: ReturnType<typeof userEvent.setup>, title = 'Consensus') {
  await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
  expect(await outcome().findByText(title, { selector: '.verdict-status' })).toBeInTheDocument()
}

describe('Arrival desk', () => {
  it('runs a fixture negotiation in a fresh environment and shows every decision', async () => {
    const user = await renderDesk()
    await runAndWait(user)

    const [{ body, key }] = server.submitted
    expect(body).toMatchObject({
      scenario_id: 'runway_closure_gate_conflict_v1',
      mode: 'stub',
      gate_occupancies: [],
      role_prompts: {},
    })
    expect(body.environment).toMatch(/^ui-[0-9a-f-]{12}$/)
    expect(key).toHaveLength(36)
    expect(body.trigger).toBeUndefined()
    expect(body.round_timeout_seconds).toBeUndefined()

    const atc = within(screen.getByRole('article', { name: 'ATC Agent, round 1' }))
    expect(atc.getByText('Complete')).toBeInTheDocument()
    expect(atc.getByText(/Sent 2 complete plans to Pilot and Ground/)).toBeInTheDocument()
    expect(atc.getByText('Preferred')).toBeInTheDocument()
    const ground = within(screen.getByRole('article', { name: 'Ground Agent, round 2' }))
    expect(ground.getAllByText(/^Accept · #/)).toHaveLength(3)
    expect(screen.getByText('3 of 4 feasible')).toBeInTheDocument()

    expect(outcome().getByRole('heading', { name: /Landing plan/ })).toBeInTheDocument()
    expect(outcome().getByText('10 min less')).toBeInTheDocument()
    expect(outcome().getByText(/3 plans were accepted by all three roles/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'events JSONL' })).toHaveAttribute(
      'href',
      `/runs/${consensus.result.run_id}/events?format=jsonl`,
    )
  })

  it('shows the constraints each agent was given', async () => {
    const user = await renderDesk()
    await runAndWait(user)
    const pilot = within(screen.getByRole('article', { name: 'Pilot Agent, round 1' }))
    await user.click(pilot.getByText('Constraints given'))
    expect(pilot.getByText('Fuel on board')).toBeInTheDocument()
    expect(pilot.getByText('6,000 kg')).toBeInTheDocument()
  })

  it('shows the simulated airport state of the chosen scenario', async () => {
    const user = await renderDesk()
    expect(screen.getByText('R1 closed until +22 min · R2 closed')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Scenario'), 'insufficient_fuel')
    expect(screen.getByText('4,300 kg (landing floor 4,000 kg)')).toBeInTheDocument()
  })

  it('flags results as stale after inputs change', async () => {
    const user = await renderDesk()
    await runAndWait(user)
    expect(screen.queryByText(/Inputs changed/)).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Scenario'), 'diversion')
    expect(screen.getByText(/Inputs changed since this run/)).toBeInTheDocument()
  })

  it('validates gate busy periods before submitting them', async () => {
    const user = await renderDesk()
    await user.click(screen.getByRole('button', { name: 'Add busy period' }))
    const until = screen.getByLabelText('Period 1 until')
    await user.clear(until)
    await user.type(until, '0')
    expect(screen.getByText('Period 1: End must be after the start.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run negotiation' })).toBeDisabled()

    await user.clear(until)
    await user.type(until, '45')
    await user.selectOptions(screen.getByLabelText('Period 1 gate'), 'B2')
    await runAndWait(user)
    expect(server.submitted[0].body.gate_occupancies).toEqual([
      { airport: 'DFW', gate_id: 'B2', start_min: 0, end_min: 45 },
    ])
  })

  it('submits the verified sample flight with the chosen scenario', async () => {
    const user = await renderDesk()
    await user.selectOptions(screen.getByLabelText('Flight'), 'real')
    expect(screen.getByText('United Air Lines Inc.')).toBeInTheDocument()
    expect(screen.getByText('506 min')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Scenario'), 'diversion')
    await runAndWait(user)
    expect(server.submitted[0].body.trigger).toMatchObject({ scenario_id: 'diversion' })
  })

  it('searches imported real flights and runs the one picked', async () => {
    const user = await renderDesk()
    await user.selectOptions(screen.getByLabelText('Flight'), 'real')
    const list = screen.getByLabelText('Matching flights')
    expect(await within(list).findAllByRole('option')).toHaveLength(2)
    expect(screen.getByText('2 of 17,310 flights.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Search disrupted DFW arrivals'), 'aus')
    await waitFor(() => expect(within(list).getAllByRole('option')).toHaveLength(1))
    await user.selectOptions(list, '2928819')
    expect(await screen.findByText('AUS to DFW')).toBeInTheDocument()
    expect(screen.getByText('UA 1356')).toBeInTheDocument()

    await runAndWait(user)
    expect(server.submitted[0].body.trigger).toMatchObject({
      flight_row: { ORIGIN_AIRPORT: 'AUS' },
      provenance: { csv_line: 2928819 },
    })
  })

  it('explains how to import flights before any are imported', async () => {
    server.flights = null
    const user = await renderDesk()
    await user.selectOptions(screen.getByLabelText('Flight'), 'real')
    expect(await screen.findByText(/to choose from every disrupted 2015 arrival/)).toBeInTheDocument()
    expect(screen.getByText('United Air Lines Inc.')).toBeInTheDocument()
  })

  it('edits, persists and resets agent prompts, sending only edits in live mode', async () => {
    server.options.live_available = true
    const user = await renderDesk()
    await user.click(screen.getByText('Agent system prompts'))
    await user.click(screen.getByRole('tab', { name: 'Pilot' }))
    const prompt = screen.getByLabelText('Pilot system prompt')
    const reset = screen.getByRole('button', { name: 'Reset to default' })
    expect(prompt).toHaveValue(server.options.default_prompts.PILOT)
    expect(reset).toBeDisabled()

    await user.clear(prompt)
    await user.type(prompt, 'Protect fuel above all.')
    expect(reset).toBeEnabled()
    expect(screen.getByText('1 edited')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Agents'), 'live')
    await runAndWait(user)
    expect(server.submitted[0].body).toMatchObject({
      mode: 'live',
      role_prompts: { PILOT: 'Protect fuel above all.' },
      round_timeout_seconds: 60,
      total_timeout_seconds: 150,
    })
    expect(JSON.parse(localStorage.getItem('bootchicks.rolePrompts')!)).toEqual({
      PILOT: 'Protect fuel above all.',
    })

    await user.click(reset)
    expect(prompt).toHaveValue(server.options.default_prompts.PILOT)
    expect(screen.queryByText('1 edited')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('bootchicks.rolePrompts')!)).toEqual({})
  })

  it('restores saved prompt edits after a reload', async () => {
    localStorage.setItem('bootchicks.rolePrompts', JSON.stringify({ ATC: 'Saved ATC prompt.' }))
    const user = await renderDesk()
    await user.click(screen.getByText('Agent system prompts'))
    expect(screen.getByLabelText('ATC system prompt')).toHaveValue('Saved ATC prompt.')
  })

  it('blocks live runs with a blank prompt and explains why', async () => {
    server.options.live_available = true
    const user = await renderDesk()
    await user.click(screen.getByText('Agent system prompts'))
    await user.clear(screen.getByLabelText('ATC system prompt'))
    expect(screen.getByText(/The ATC prompt is empty/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run negotiation' })).toBeEnabled()
    await user.selectOptions(screen.getByLabelText('Agents'), 'live')
    expect(screen.getByRole('button', { name: 'Run negotiation' })).toBeDisabled()
    expect(screen.getByText('Every agent needs a system prompt.')).toBeInTheDocument()
  })

  it('disables Claude agents when the server has no API key', async () => {
    await renderDesk()
    expect(screen.getByRole('option', { name: /Claude agents/ })).toBeDisabled()
    expect(screen.getByText(/ANTHROPIC_API_KEY/)).toBeInTheDocument()
  })

  it('shows a non-committable review warning after conditional votes', async () => {
    server.fixture = escalated
    const user = await renderDesk()
    await runAndWait(user, 'Human review required')
    expect(outcome().getByRole('heading', { name: /Do not execute - human review required/i })).toBeInTheDocument()
    expect(outcome().getByText(/plans; none passed. Most frequent failures/)).toBeInTheDocument()
    expect(outcome().queryByRole('heading', { name: /Landing plan/ })).not.toBeInTheDocument()
    const round2 = within(screen.getByRole('article', { name: 'ATC Agent, round 2' }))
    expect(round2.getByText('Complete')).toBeInTheDocument()
    expect(round2.getAllByText(/Support if remediated/).length).toBeGreaterThan(0)
  })

  it('shows a diversion chosen without agents', async () => {
    server.fixture = fallback
    const user = await renderDesk()
    await runAndWait(user, 'Fallback plan')
    expect(outcome().getByRole('heading', { name: /Diversion to DAL/ })).toBeInTheDocument()
    expect(screen.getAllByText('Skipped')).toHaveLength(7)
  })

  it('shows server validation errors and unreachable servers clearly', async () => {
    const user = await renderDesk()
    vi.mocked(fetch).mockImplementationOnce(() =>
      json({ detail: 'Unknown gate DFW/Z9 in this scenario.' }, 422),
    )
    await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
    expect(await screen.findByText(/Unknown gate DFW\/Z9 in this scenario./)).toBeInTheDocument()

    vi.mocked(fetch).mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')))
    render(<App />)
    expect(await screen.findByText(/Cannot reach the BootChicks server/)).toBeInTheDocument()
  })

  it('replays a fast run stage by stage and keeps the current stage in view', async () => {
    const user = await renderDesk(60)
    expect(currentStage()).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
    expect(screen.getByRole('button', { name: 'Negotiating...' })).toBeDisabled()

    const seen: string[] = []
    await waitFor(
      () => {
        const name = currentStage()
        if (name && seen.at(-1) !== name) seen.push(name)
        expect(outcome().queryByText('Consensus', { selector: '.verdict-status' })).toBeInTheDocument()
      },
      { timeout: 4000, interval: 15 },
    )
    expect(seen).toEqual(STAGES)
    expect(within(stage('Round 1 - Proposals')).getAllByText('Complete')).toHaveLength(3)

    expect(currentStage()).toBeNull()
    expect(screen.queryByRole('button', { name: 'Skip replay' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run negotiation' })).toBeEnabled()
    expect(new Set(scrolledTo())).toEqual(
      new Set(['round1-stage-title', 'board-stage-title', 'round2-stage-title', 'decision-stage-title']),
    )
  })

  it('shows the whole run at once when the replay is skipped', async () => {
    const user = await renderDesk(60_000)
    await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
    await user.click(await screen.findByRole('button', { name: 'Skip replay' }))
    expect(outcome().getByText('Consensus', { selector: '.verdict-status' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Skip replay' })).not.toBeInTheDocument()
    expect(currentStage()).toBeNull()
  })

  it('stops following the stages once the user scrolls', async () => {
    const user = await renderDesk(60)
    await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
    fireEvent.wheel(window)
    expect(await outcome().findByText('Consensus', { selector: '.verdict-status' }, { timeout: 4000 })).toBeInTheDocument()
    expect(scrolledTo()).toEqual(['round1-stage-title'])
  })

  it('animates the connector leading into the current stage only', async () => {
    const user = await renderDesk(60_000)
    await user.click(screen.getByRole('button', { name: 'Run negotiation' }))
    await screen.findByRole('button', { name: 'Skip replay' })
    const live = document.querySelectorAll('.connector.is-live')
    expect(live).toHaveLength(1)
    expect(stage('Round 1 - Proposals')).toContainElement(live[0] as HTMLElement)
    expect(live[0].querySelectorAll('.bit')).not.toHaveLength(0)
  })

  it('keeps the page header to the essentials', async () => {
    await renderDesk()
    expect(screen.queryByRole('button', { name: 'Demo' })).not.toBeInTheDocument()
    expect(screen.queryByText('Input')).not.toBeInTheDocument()
    expect(screen.queryByText(/Demo flight ·/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Python checks/)).not.toBeInTheDocument()
  })
})
