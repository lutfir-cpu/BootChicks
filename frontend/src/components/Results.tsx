import { Fragment } from 'react'
import {
  clockTime,
  formatCheckValue,
  formatNumber,
  improvements,
  minutesAfter,
  MODE_NAMES,
  reasonText,
  ROLE_NAMES,
  STATUS_TEXT,
} from '../labels'
import { runwayOf, type AgentTurn, type Negotiation } from '../negotiation'
import {
  ROLES,
  type Action,
  type CandidateEvaluation,
  type CheckResult,
  type Role,
  type RunResult,
} from '../types'

export function Outcome({ result, stale }: { result: RunResult; stale: boolean }) {
  const text = STATUS_TEXT[result.status]
  const started = result.fallback_reason && result.status !== 'CONSENSUS'
  return (
    <section className={`outcome outcome-${result.status.toLowerCase()}`} aria-live="polite">
      <div className="outcome-head">
        <h2>{text.title}</h2>
        <span className="outcome-mode">{MODE_NAMES[result.mode]}</span>
      </div>
      <p className="outcome-summary">{text.summary}</p>
      {started && <p className="outcome-reason">{reasonText(result.terminal_reason)}</p>}
      <dl className="stats">
        <Stat label="Rounds" value={String(result.rounds_used)} />
        <Stat label="Agent responses" value={String(result.logical_agent_responses)} />
        <Stat label="Model requests" value={String(result.provider_requests)} />
        <Stat label="Time" value={`${formatNumber(result.latency_ms / 1000, 2)} s`} />
      </dl>
      {stale && (
        <p className="stale" role="status">
          Inputs changed since this run. Run again to see their effect.
        </p>
      )}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function PlanSummary({ result, view }: { result: RunResult; view: Negotiation }) {
  const evaluation = result.evaluation
  const plan = result.selected_plan
  if (!plan || !evaluation?.outcomes) return null
  const o = evaluation.outcomes
  const a = plan.action
  const gains = result.improvement_metrics ? improvements(result.improvement_metrics) : []
  return (
    <section className="card">
      <h3>
        {a.action === 'DIVERT' ? `Diversion to ${a.airport}` : 'Landing plan'}
        <span className="mono subtle"> {plan.candidate_id}</span>
      </h3>
      <dl className="plan-grid">
        <Item label="Airport" value={a.airport} />
        <Item label="Runway" value={runwayOf(view, a.airport, a.taxi_path_id) ?? '-'} />
        <Item label="Touchdown" value={clockTime(o.touchdown)} note={minutesAfter(o.touchdown, view.clock)} />
        <Item label="At gate" value={clockTime(o.gate_arrival)} note={minutesAfter(o.gate_arrival, view.clock)} />
        <Item label="Gate" value={a.gate_id} />
        <Item label="Taxi route" value={a.taxi_path_id} note={`${formatNumber(o.taxi_min)} min`} />
        <Item label="Approach" value={a.approach_id} />
        <Item label="Crew" value={a.crew_id} />
      </dl>
      <dl className="plan-grid outcomes">
        <Item label="Holding" value={`${formatNumber(o.holding_min)} min`} />
        <Item label="Airborne fuel" value={`${formatNumber(o.airborne_fuel_kg)} kg`} />
        <Item label="Landing fuel margin" value={`${formatNumber(o.landing_margin_kg)} kg`} />
        <Item label="Gate wait" value={`${formatNumber(o.gate_wait_min)} min`} />
        <Item label="Crew overtime" value={`${formatNumber(o.overtime_min)} min`} />
        <Item label="Missed connections" value={`${formatNumber(o.missed_connections)} pax`} />
      </dl>
      {gains.length > 0 && (
        <div className="baseline">
          <h4>Compared with the baseline plan</h4>
          <ul>
            {gains.map((gain) => (
              <li key={gain.label} className={`tone-${gain.tone}`}>
                <span>{gain.label}</span>
                <strong>{gain.text}</strong>
              </li>
            ))}
          </ul>
          <p className="hint">
            The baseline is the best plan under the same rules without negotiation. Simulator outcomes, not measured
            airline savings.
          </p>
        </div>
      )}
    </section>
  )
}

function Item({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value}
        {note && <span className="subtle"> {note}</span>}
      </dd>
    </div>
  )
}

function actionText(view: Negotiation, action: Action): string {
  const runway = runwayOf(view, action.airport, action.taxi_path_id)
  return `${clockTime(action.landing_slot)} · ${runway ?? action.airport} · gate ${action.gate_id}`
}

function RoleTag({ role }: { role: Role }) {
  return <span className={`role role-${role.toLowerCase()}`}>{ROLE_NAMES[role]}</span>
}

export function Timeline({ result, view }: { result: RunResult; view: Negotiation }) {
  const round1 = view.rounds[1]
  const round2 = view.rounds[2]
  if (!round1) {
    return (
      <section className="card">
        <h3>Negotiation</h3>
        <p className="hint">{reasonText(view.fallbackStarted)} No agent messages were exchanged.</p>
        <Rejections view={view} />
      </section>
    )
  }
  return (
    <section className="card timeline">
      <h3>Negotiation</h3>
      <ol className="steps">
        <li>
          <h4>
            Round 1 <span className="subtle">- each role proposes up to three complete plans</span>
          </h4>
          <div className="role-columns">
            {ROLES.map((role) => (
              <ProposalColumn key={role} role={role} turn={round1[role]} view={view} />
            ))}
          </div>
        </li>
        {view.board && (
          <li>
            <h4>
              Python checks <span className="subtle">- every distinct proposal against the hard rules</span>
            </h4>
            <Board board={view.board} view={view} selectedHash={result.selected_plan?.plan_hash ?? null} />
          </li>
        )}
        {round2 && view.board && (
          <li>
            <h4>
              Round 2 <span className="subtle">- each role votes on every feasible plan</span>
            </h4>
            <Votes round={round2} board={view.board} view={view} selectedHash={view.selectedHash} />
          </li>
        )}
        <li>
          <h4>Decision</h4>
          <Decision result={result} view={view} />
        </li>
      </ol>
    </section>
  )
}

function ProposalColumn({ role, turn, view }: { role: Role; turn?: AgentTurn; view: Negotiation }) {
  return (
    <div className="role-column">
      <RoleTag role={role} />
      {turn?.absentReason && <p className="field-error">No reply: {reasonText(turn.absentReason)}</p>}
      {turn && !turn.absentReason && turn.proposals.length === 0 && (
        <p className="hint">No proposals.</p>
      )}
      {turn?.proposals.map((proposal, index) => (
        <div key={index} className="proposal">
          <div className="proposal-head">
            <span className="chip">{proposal.label}</span>
            <span className="mono">{actionText(view, proposal.action)}</span>
          </div>
          <p>{proposal.rationale}</p>
        </div>
      ))}
    </div>
  )
}

function Board({
  board,
  view,
  selectedHash,
}: {
  board: CandidateEvaluation[]
  view: Negotiation
  selectedHash: string | null
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Plan</th>
            <th>Landing</th>
            <th>Gate</th>
            <th>Proposed by</th>
            <th>Hard checks</th>
          </tr>
        </thead>
        <tbody>
          {board.map((evaluation) => {
            const failed = evaluation.checks.filter((c) => !c.passed)
            const c = evaluation.candidate
            return (
              <tr key={c.plan_hash} className={c.plan_hash === selectedHash ? 'selected' : undefined}>
                <td className="mono">{c.candidate_id.slice(0, 8)}</td>
                <td className="mono">
                  {clockTime(c.action.landing_slot)} {runwayOf(view, c.action.airport, c.action.taxi_path_id)}
                </td>
                <td className="mono">{c.action.gate_id}</td>
                <td>
                  {c.proposers.map((role) => (
                    <RoleTag key={role} role={role} />
                  ))}
                </td>
                <td>
                  {failed.length === 0 ? (
                    <span className="pass">All {evaluation.checks.length} pass</span>
                  ) : (
                    <span className="fail" title={failed.map((f) => f.constraint_id).join(', ')}>
                      {failed.length} fail: {failed.slice(0, 2).map((f) => f.constraint_id).join(', ')}
                      {failed.length > 2 && ', ...'}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Votes({
  round,
  board,
  view,
  selectedHash,
}: {
  round: Partial<Record<Role, AgentTurn>>
  board: CandidateEvaluation[]
  view: Negotiation
  selectedHash: string | null
}) {
  const feasible = board.filter((e) => e.feasible)
  const voteOf = (role: Role, hash: string) => round[role]?.votes.find((v) => v.plan_hash === hash)
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Plan</th>
              {ROLES.map((role) => (
                <th key={role}>
                  <RoleTag role={role} />
                </th>
              ))}
              <th>All accept</th>
            </tr>
          </thead>
          <tbody>
            {feasible.map((e) => {
              const hash = e.candidate.plan_hash
              const unanimous = ROLES.every((role) => voteOf(role, hash)?.decision === 'ACCEPT')
              return (
                <tr key={hash} className={hash === selectedHash ? 'selected' : undefined}>
                  <td className="mono">
                    {e.candidate.candidate_id.slice(0, 8)}{' '}
                    <span className="subtle">{actionText(view, e.candidate.action)}</span>
                  </td>
                  {ROLES.map((role) => {
                    const vote = voteOf(role, hash)
                    if (round[role]?.absentReason) return <td key={role} className="subtle">no reply</td>
                    if (!vote) return <td key={role} className="subtle">-</td>
                    return (
                      <td key={role} className={vote.decision === 'ACCEPT' ? 'pass' : 'fail'}>
                        {vote.decision === 'ACCEPT' ? 'Accept' : 'Reject'}{' '}
                        <span className="subtle">#{vote.preference_rank}</span>
                      </td>
                    )
                  })}
                  <td className={unanimous ? 'pass' : 'subtle'}>{unanimous ? 'Yes' : 'No'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <details className="rationales">
        <summary>Vote rationales</summary>
        {ROLES.map((role) => (
          <div key={role} className="rationale">
            <RoleTag role={role} />
            {round[role]?.votes.map((vote) => (
              <p key={vote.plan_hash}>
                <span className="mono">{vote.candidate_id.slice(0, 8)}</span> {vote.rationale}
                {vote.accepted_concessions.length > 0 && (
                  <span className="subtle"> Concession: {vote.accepted_concessions.join(' ')}</span>
                )}
              </p>
            ))}
          </div>
        ))}
      </details>
    </>
  )
}

function Decision({ result, view }: { result: RunResult; view: Negotiation }) {
  return (
    <div className="decision">
      {view.unanimous && (
        <p>
          {view.unanimous.length === 1
            ? 'One plan was accepted by all three roles.'
            : `${view.unanimous.length} plans were accepted by all three roles; the fairness rule picked the one with the lowest worst-case domain cost.`}
        </p>
      )}
      {view.noUnanimousPlan && <p>No feasible plan was accepted by all three roles.</p>}
      {view.fallbackStarted && (
        <p>
          Deterministic fallback started: {reasonText(view.fallbackStarted)}
        </p>
      )}
      {view.commit && (
        <p>
          Revalidated against current airport state and committed {view.commit.reservations} resource
          reservations (state <span className="mono">{view.commit.snapshotBefore.split(':')[1]}</span> to{' '}
          <span className="mono">{view.commit.snapshotAfter.split(':')[1]}</span>).
        </p>
      )}
      {result.consensus_certificate && (
        <p className="hint">
          Consensus certificate binds plan <span className="mono">{result.consensus_certificate.plan_hash.slice(0, 12)}</span>{' '}
          to the three accepting vote messages and the commit event.
        </p>
      )}
      <Rejections view={view} />
    </div>
  )
}

function Rejections({ view }: { view: Negotiation }) {
  if (view.rejections.length === 0) return null
  const counts = new Map<string, number>()
  for (const rejection of view.rejections) {
    for (const check of rejection.failed) {
      counts.set(check.constraint_id, (counts.get(check.constraint_id) ?? 0) + 1)
    }
  }
  const common = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
  return (
    <div className="rejections">
      <p>
        The fallback tried {formatNumber(view.rejections.length)} plans at the destination and alternate; none passed.
        Most frequent failures:
      </p>
      <ul>
        {common.map(([id, count]) => (
          <li key={id}>
            <span className="mono">{id}</span> <span className="subtle">in {formatNumber(count)} plans</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Checks({ checks }: { checks: CheckResult[] }) {
  const failed = checks.filter((c) => !c.passed).length
  return (
    <details className="card checks">
      <summary>
        <h3>Hard checks for the chosen plan</h3>
        <span className={failed ? 'fail' : 'pass'}>
          {failed ? `${failed} of ${checks.length} fail` : `All ${checks.length} pass`}
        </span>
      </summary>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Check</th>
              <th>Owner</th>
              <th>Measured</th>
              <th>Limit</th>
              <th className="num">Margin</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {ROLES.map((role) => (
              <Fragment key={role}>
                {checks
                  .filter((c) => c.domain === role)
                  .map((check) => (
                    <tr key={`${check.constraint_id}-${check.source_reference}`}>
                      <td className="mono" title={check.source_reference}>
                        {check.constraint_id}
                      </td>
                      <td>
                        <RoleTag role={role} />
                      </td>
                      <td className="value">{formatCheckValue(check.measured, check.unit)}</td>
                      <td className="value">{formatCheckValue(check.bound, check.unit)}</td>
                      <td className="num">{check.margin === null ? '-' : formatCheckValue(check.margin, check.unit)}</td>
                      <td className={check.passed ? 'pass' : 'fail'}>{check.passed ? 'Pass' : 'Fail'}</td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

export function AuditLinks({ runId }: { runId: string }) {
  return (
    <p className="audit">
      Audit trail: <a href={`/runs/${runId}`}>result JSON</a> · <a href={`/runs/${runId}/events?format=jsonl`}>events JSONL</a>
      <span className="subtle mono"> run {runId.slice(0, 8)}</span>
    </p>
  )
}
