import type {
  AuditEvent,
  CandidateEvaluation,
  CheckResult,
  Proposal,
  Role,
  TaxiPath,
  Vote,
} from './types'

export interface AgentTurn {
  role: Role
  absentReason?: string
  proposals: Proposal[]
  votes: Vote[]
  provider?: string
  promptVersion?: string
}

export interface Rejection {
  plan_hash: string
  failed: CheckResult[]
}

export interface Negotiation {
  clock: string | null
  /** Taxi paths keyed by `${airport}:${path id}`, used to name the runway of a plan. */
  paths: Record<string, TaxiPath>
  preferredGate: string | null
  rounds: Partial<Record<1 | 2, Partial<Record<Role, AgentTurn>>>>
  board: CandidateEvaluation[] | null
  unanimous: string[] | null
  noUnanimousPlan: boolean
  selectedHash: string | null
  fallbackStarted: string | null
  rejections: Rejection[]
  commit: { snapshotBefore: string; snapshotAfter: string; reservations: number } | null
}

interface SnapshotAirport {
  iata_code: string
  paths: TaxiPath[]
}

/** Rebuild the two-round negotiation from the run's ordered audit events. */
export function readNegotiation(events: AuditEvent[]): Negotiation {
  const view: Negotiation = {
    clock: null,
    paths: {},
    preferredGate: null,
    rounds: {},
    board: null,
    unanimous: null,
    noUnanimousPlan: false,
    selectedHash: null,
    fallbackStarted: null,
    rejections: [],
    commit: null,
  }
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const p = event.payload
    switch (event.kind) {
      case 'PREPARED': {
        const snapshot = p.snapshot as {
          clock: string
          preferred_gate: string
          destination: SnapshotAirport
          alternates: SnapshotAirport[]
        }
        view.clock = snapshot.clock
        view.preferredGate = snapshot.preferred_gate
        for (const airport of [snapshot.destination, ...snapshot.alternates]) {
          for (const path of airport.paths) view.paths[`${airport.iata_code}:${path.id}`] = path
        }
        break
      }
      case 'AGENT_MESSAGE': {
        const round = p.round as 1 | 2
        const role = p.sender as Role
        const response = p.response as { proposals?: Proposal[]; votes?: Vote[] }
        turnFor(view, round, role).proposals = response.proposals ?? []
        turnFor(view, round, role).votes = response.votes ?? []
        turnFor(view, round, role).provider = p.provider as string
        turnFor(view, round, role).promptVersion = p.prompt_version as string
        break
      }
      case 'AGENT_ABSENT':
        turnFor(view, p.round as 1 | 2, p.sender as Role).absentReason = p.reason as string
        break
      case 'PROPOSAL_BOARD':
        view.board = p.evaluations as CandidateEvaluation[]
        break
      case 'NO_UNANIMOUS_PLAN':
        view.noUnanimousPlan = true
        break
      case 'SELECTION':
        view.unanimous = p.unanimous_candidates as string[]
        view.selectedHash = p.selected_hash as string
        break
      case 'FALLBACK_STARTED':
        view.fallbackStarted = p.reason as string
        break
      case 'NO_VALIDATED_PLAN':
        view.rejections = p.rejections as Rejection[]
        break
      case 'RESOURCE_COMMIT':
        view.commit = {
          snapshotBefore: p.snapshot_before as string,
          snapshotAfter: p.snapshot_after as string,
          reservations: (p.reservations as unknown[]).length,
        }
        break
    }
  }
  return view
}

function turnFor(view: Negotiation, round: 1 | 2, role: Role): AgentTurn {
  const roles = (view.rounds[round] ??= {})
  return (roles[role] ??= { role, proposals: [], votes: [] })
}

/** The runway a plan lands on, read from its taxi path. */
export function runwayOf(view: Negotiation, airport: string, taxiPathId: string): string | null {
  return view.paths[`${airport}:${taxiPathId}`]?.runway_id ?? null
}
