// Mirrors the JSON shapes of src/bootchicks/schemas.py and api.py.

export type Role = 'ATC' | 'PILOT' | 'GROUND'
export const ROLES: readonly Role[] = ['ATC', 'PILOT', 'GROUND']

export type Mode = 'stub' | 'live' | 'fallback'

export interface ScenarioAirport {
  iata_code: string
  kind: 'destination' | 'alternate'
  gates: string[]
}

export interface ScenarioOption {
  id: string
  label: string
  description: string
  preferred_gate: string
  airports: ScenarioAirport[]
}

export interface WorkflowInput {
  scenario_id: string
  flight_row: Record<string, unknown> & {
    AIRLINE: string
    FLIGHT_NUMBER: string | number
    ORIGIN_AIRPORT: string
    DESTINATION_AIRPORT: string
    YEAR: number
    MONTH: number
    DAY: number
  }
  provenance: { csv_line: number | null }
  [key: string]: unknown
}

export interface Options {
  scenarios: ScenarioOption[]
  live_available: boolean
  model: string
  default_prompts: Record<Role, string>
  prompt_version: string
  sample_trigger: WorkflowInput
}

export interface GateOccupancy {
  airport: string
  gate_id: string
  start_min: number
  end_min: number
}

export interface RunRequest {
  scenario_id: string
  mode: Mode
  environment: string
  gate_occupancies: GateOccupancy[]
  role_prompts: Partial<Record<Role, string>>
  trigger?: WorkflowInput
}

export interface Action {
  action: 'LAND' | 'DIVERT'
  airport: string
  landing_slot: string
  approach_id: string
  taxi_path_id: string
  gate_id: string
  crew_id: string
}

export interface CandidatePlan {
  candidate_id: string
  plan_hash: string
  snapshot_version: string
  action: Action
  proposers: Role[]
}

export interface CheckResult {
  constraint_id: string
  domain: Role
  passed: boolean
  measured: number | string | boolean | null
  bound: number | string | boolean | null
  unit: string
  margin: number | null
  source_reference: string
}

export interface Outcomes {
  touchdown: string
  gate_arrival: string
  service_end: string
  holding_min: number
  airborne_fuel_kg: number
  fuel_touchdown_kg: number
  fuel_gate_kg: number
  landing_margin_kg: number
  gate_margin_kg: number
  taxi_min: number
  gate_wait_min: number
  missed_connections: number
  missed_connection_fraction: number
  overtime_min: number
  next_departure_delay_min: number
}

export interface CandidateEvaluation {
  candidate: CandidatePlan
  feasible: boolean
  checks: CheckResult[]
  outcomes: Outcomes | null
  domain_costs: Partial<Record<Role, number>>
}

export type RunStatus = 'CONSENSUS' | 'FALLBACK' | 'ESCALATED' | 'FAILED'

export interface RunResult {
  run_id: string
  status: RunStatus
  terminal_reason: string
  mode: Mode | 'recorded_replay'
  source_provenance: { source_type: 'historical_csv' | 'synthetic_fixture'; csv_line: number | null }
  snapshot_version: string
  rounds_used: number
  logical_agent_responses: number
  provider_requests: number
  latency_ms: number
  selected_plan: CandidatePlan | null
  evaluation: CandidateEvaluation | null
  consensus_certificate: {
    plan_hash: string
    accepting_messages: Record<Role, string>
    commit_event_id: string
  } | null
  fallback_reason: string | null
  baseline: CandidateEvaluation | null
  improvement_metrics: Record<string, number> | null
}

export interface RunState {
  run_id: string
  status: 'QUEUED' | 'RUNNING' | RunStatus
  result: RunResult | null
}

export interface AuditEvent {
  event_id: string
  sequence: number
  kind: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface Proposal {
  label: 'preferred' | 'compromise' | 'concession'
  action: Action
  rationale: string
  requested_concessions: string[]
}

export interface Vote {
  candidate_id: string
  plan_hash: string
  decision: 'ACCEPT' | 'REJECT'
  preference_rank: number
  reason_codes: string[]
  rationale: string
  accepted_concessions: string[]
}

export interface TaxiPath {
  id: string
  runway_id: string
  gate_id: string
}
