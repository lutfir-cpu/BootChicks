import { actionText, clockTime, ROLE_NAMES } from '../labels'
import { agentLog, agentStatus, skippedReason, type RunView } from '../trace'
import type { AgentDecision, Given, Proposal, Role, Vote } from '../types'
import { DataLine, Loading, LogPanel, Panel, StatusBadge } from './Layout'

const LABELS: Record<Proposal['label'], string> = {
  preferred: 'Preferred',
  compromise: 'Compromise',
  concession: 'Concession',
}

function GivenRow({ given, round }: { given: Given[]; round: 1 | 2 }) {
  return (
    <details className="plan-row given">
      <summary>
        <span>{round === 1 ? 'Constraints given' : 'Board given'}</span>
        <span className="plan-stance">{given.length} items</span>
      </summary>
      <div className="plan-fields">
        {given.map((item) => (
          <DataLine key={item.label} label={item.label} value={item.value} />
        ))}
      </div>
    </details>
  )
}

function ProposalRow({ proposal }: { proposal: Proposal }) {
  const a = proposal.action
  return (
    <details className="plan-row">
      <summary>
        <span className="mono">{actionText(a)}</span>
        <span className="plan-stance">{LABELS[proposal.label]}</span>
      </summary>
      <div className="plan-fields">
        <DataLine label="Action" value={a.action === 'DIVERT' ? `Divert to ${a.airport}` : `Land at ${a.airport}`} />
        <DataLine label="Landing slot" value={clockTime(a.landing_slot)} />
        <DataLine label="Runway" value={a.runway_id ?? '-'} />
        <DataLine label="Approach" value={a.approach_id} />
        <DataLine label="Taxi route" value={a.taxi_path_id} />
        <DataLine label="Gate" value={a.gate_id} />
        <DataLine label="Crew" value={a.crew_id} />
        <p className="reasoning">{proposal.rationale}</p>
        {proposal.requested_concessions.length > 0 && (
          <p className="reasoning subtle">Asks others to concede: {proposal.requested_concessions.join(' ')}</p>
        )}
      </div>
    </details>
  )
}

function VoteRow({ vote }: { vote: Vote }) {
  const supported = vote.decision !== 'REJECT'
  const label = {
    ACCEPT: 'Accept',
    REJECT: 'Reject',
    SUPPORT_IF_AUTHORIZED: 'Support if authorized',
    SUPPORT_IF_REMEDIATED: 'Support if remediated',
  }[vote.decision]
  return (
    <details className="plan-row">
      <summary>
        <span className="mono">{vote.action ? actionText(vote.action) : vote.candidate_id.slice(0, 8)}</span>
        <span className={`plan-stance ${supported ? 'pass' : 'fail'}`}>
          {label} · #{vote.preference_rank}
        </span>
      </summary>
      <div className="plan-fields">
        <DataLine label="Plan" value={<span className="mono">{vote.candidate_id.slice(0, 8)}</span>} />
        <DataLine label="Preference rank" value={`#${vote.preference_rank}`} />
        {vote.reason_codes.length > 0 && <DataLine label="Reason codes" value={vote.reason_codes.join(', ')} />}
        <p className="reasoning">{vote.rationale}</p>
        {vote.accepted_concessions.length > 0 && (
          <p className="reasoning subtle">Accepted concession: {vote.accepted_concessions.join(' ')}</p>
        )}
      </div>
    </details>
  )
}

function Decided({ agent, round }: { agent: AgentDecision; round: 1 | 2 }) {
  if (round === 1) {
    return agent.proposals.length ? (
      agent.proposals.map((proposal, index) => <ProposalRow key={index} proposal={proposal} />)
    ) : (
      <p className="empty-value">No proposals.</p>
    )
  }
  return agent.votes.length ? (
    agent.votes.map((vote) => <VoteRow key={vote.plan_hash} vote={vote} />)
  ) : (
    <p className="empty-value">No votes.</p>
  )
}

export function AgentCard({ role, round, run }: { role: Role; round: 1 | 2; run: RunView | null }) {
  const status = agentStatus(run, round, role)
  const agent = run?.log.rounds[round]?.agents[role]
  const name = `${ROLE_NAMES[role]} Agent`
  return (
    <article className="card agent-card" aria-label={`${name}, round ${round}`}>
      <div className="agent-head">
        <h3>{name}</h3>
        <StatusBadge status={status} />
      </div>
      <LogPanel label={`${name} round ${round} logs`} lines={run ? agentLog(run, round, role) : []} />
      <Panel title={round === 1 ? 'Proposals' : 'Votes'}>
        {agent && <GivenRow given={agent.given} round={round} />}
        {status === 'complete' && agent && <Decided agent={agent} round={round} />}
        {status === 'running' && (
          <Loading>{round === 1 ? 'Drafting complete plans...' : 'Reviewing the board...'}</Loading>
        )}
        {status === 'error' && (
          <p className="error-message" role="alert">
            No reply. {agent?.absent_reason}
          </p>
        )}
        {status === 'skipped' && run && <p className="empty-value">{skippedReason(run)}</p>}
        {status === 'waiting' && <p className="empty-value">Waiting.</p>}
        {agent?.provider && (
          <p className="provenance">
            {agent.model ? `${agent.provider} · ${agent.model}` : agent.provider}
            {agent.custom_prompt && <span className="count-badge">Edited prompt</span>}
          </p>
        )}
      </Panel>
    </article>
  )
}
