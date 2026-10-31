// The fields the UI reads from the API; see src/bootchicks/schemas.py and api.py for the full shapes.

export type Role = 'ATC' | 'PILOT' | 'GROUND'
export const ROLES: readonly Role[] = ['ATC', 'PILOT', 'GROUND']

export type Mode = 'stub' | 'live' | 'fallback'

/** A window in minutes after the scenario clock. */
export interface MinuteWindow {
  start_min: number
  end_min: number
}

export interface ScenarioAirport {
  iata_code: string
  kind: 'destination' | 'alternate'
  gates: string[]
  runways: { id: string; closed: MinuteWindow[] }[]
  crews: number
}

export interface ScenarioOption {
  id: string
  label: string
  description: string
  preferred_gate: string
  window_min: number
  aircraft: { type_label: string; fuel_kg: number; protected_landing_kg: number }
  airports: ScenarioAirport[]
}

interface WorkflowInput {
  scenario_id: string
  flight_row: Record<string, unknown> & {
    AIRLINE: string
    FLIGHT_NUMBER: string | number
    TAIL_NUMBER: string | null
    ORIGIN_AIRPORT: string
    DESTINATION_AIRPORT: string
    YEAR: number
    MONTH: number
    DAY: number
    SCHEDULED_ARRIVAL: number
    ARRIVAL_DELAY: number | null
  }
  airline_row: { AIRLINE: string }
  provenance: { csv_line: number | null }
  [key: string]: unknown
}

export interface Options {
  scenarios: ScenarioOption[]
  live_available: boolean
  model: string
  default_prompts: Record<Role, string>
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
  round_timeout_seconds?: number
  total_timeout_seconds?: number
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

interface CandidatePlan {
  candidate_id: string
  plan_hash: string
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
  classification: 'HARD_SAFETY' | 'AUTHORIZATION_REQUIRED'
  review_policy_version: string
}

interface Outcomes {
  touchdown: string
  gate_arrival: string
  holding_min: number
  airborne_fuel_kg: number
  landing_margin_kg: number
  taxi_min: number
  gate_wait_min: number
  missed_connections: number
  overtime_min: number
}

export interface CandidateEvaluation {
  candidate: CandidatePlan
  feasible: boolean
  checks: CheckResult[]
  outcomes: Outcomes | null
  review_status: 'SAFE' | 'REQUIRES_AUTHORIZATION' | 'SAFETY_BLOCKED'
}

export type RunStatus = 'CONSENSUS' | 'FALLBACK' | 'REVIEW_REQUIRED' | 'ESCALATED' | 'FAILED'

export interface RunResult {
  run_id: string
  status: RunStatus
  terminal_reason: string
  mode: Mode | 'recorded_replay'
  rounds_used: number
  logical_agent_responses: number
  provider_requests: number
  latency_ms: number
  selected_plan: CandidatePlan | null
  evaluation: CandidateEvaluation | null
  consensus_certificate: { plan_hash: string } | null
  review_recommendation: {
    candidate: CandidatePlan
    evaluation: CandidateEvaluation
    required_action: 'AUTHORIZE' | 'REMEDIATE'
    supporting_messages: Record<Role, string>
  } | null
  human_review_required: boolean
  fallback_reason: string | null
  improvement_metrics: Record<string, number> | null
}

export interface RunState {
  status: 'QUEUED' | 'RUNNING' | RunStatus
  result: RunResult | null
}

export interface Given {
  label: string
  value: string
}

/** A plan action with the runway its taxi path starts from. */
export interface PlannedAction extends Action {
  runway_id: string | null
}

export interface Proposal {
  label: 'preferred' | 'compromise' | 'concession'
  action: PlannedAction
  rationale: string
  requested_concessions: string[]
}

export interface Vote {
  candidate_id: string
  plan_hash: string
  action: PlannedAction | null
  decision: 'ACCEPT' | 'REJECT' | 'SUPPORT_IF_AUTHORIZED' | 'SUPPORT_IF_REMEDIATED'
  preference_rank: number
  reason_codes: string[]
  rationale: string
  accepted_concessions: string[]
}

export interface AgentDecision {
  status: 'DECIDING' | 'DECIDED' | 'NO_REPLY'
  received_at: string
  decided_at: string | null
  given: Given[]
  custom_prompt: boolean
  provider: string | null
  model: string | null
  prompt_version: string
  proposals: Proposal[]
  votes: Vote[]
  absent_reason: string | null
}

export interface BoardCandidate {
  candidate_id: string
  plan_hash: string
  action: PlannedAction
  proposers: Role[]
  feasible: boolean
  review_status: CandidateEvaluation['review_status']
  checks: CheckResult[]
}

export interface TimelineEntry {
  sequence: number
  at: string
  actor: Role | 'SYSTEM'
  round: 1 | 2 | null
  kind: string
  message: string
}

/** GET /runs/{id}/decisions: what each agent was given, decided and why, then what Python decided. */
export interface DecisionLog {
  run_id: string
  status: RunState['status']
  finished: boolean
  flight_id: string | null
  clock: string | null
  rounds: Partial<Record<'1' | '2', { started_at: string; agents: Record<Role, AgentDecision> }>>
  board: { at: string; candidates: BoardCandidate[] } | null
  decision: {
    baseline_feasible: boolean | null
    unanimous_candidates: string[] | null
    selected_hash: string | null
    domain_costs: Record<Role, number> | null
    fairness_policy: string | null
    no_unanimous_plan: boolean
    fallback_reason: string | null
    rejections: { plans: number; most_common: { constraint_id: string; plans: number }[] } | null
    commit: {
      plan_hash: string
      runway_id: string | null
      snapshot_before: string
      snapshot_after: string
      reservations: number
    } | null
    review_recommendation: {
      candidate_id: string
      plan_hash: string
      action: PlannedAction
      required_action: 'AUTHORIZE' | 'REMEDIATE'
      review_status: CandidateEvaluation['review_status']
      failed_checks: CheckResult[]
    } | null
    terminal: { status: RunStatus; reason: string; reason_text: string } | null
  }
  timeline: TimelineEntry[]
}
