import { Fragment, type Ref } from 'react'
import {
  clockTime,
  formatCheckValue,
  formatNumber,
  improvements,
  minutesAfter,
  MODE_NAMES,
  planHeadline,
  ROLE_NAMES,
  STATUS_TEXT,
} from '../labels'
import { systemLog, type RunView } from '../trace'
import { ROLES, type CheckResult, type DecisionLog, type RunResult } from '../types'
import { DataLine, Loading, LogPanel, RoleTag, StatusBadge } from './Layout'

const CHECK_CLASS: Record<CheckResult['classification'], string> = {
  HARD_SAFETY: 'Safety',
  AUTHORIZATION_REQUIRED: 'Authorization',
}

export function DecisionCard({
  run,
  stale,
  traceRef,
}: {
  run: RunView | null
  stale: boolean
  traceRef: Ref<HTMLDetailsElement>
}) {
  const result = run?.result
  return (
    <article className="card wide-card" aria-label="Outcome">
      {result && run ? (
        <Verdict result={result} log={run.log} />
      ) : (
        <div className="agent-head">
          <h3>Outcome</h3>
          <StatusBadge status={run ? 'running' : 'waiting'} />
        </div>
      )}
      <div className="agent-body">
        {result && run ? (
          <Outcome result={result} log={run.log} stale={stale} />
        ) : run ? (
          <Loading offset={4} />
        ) : (
          <p className="empty-value">Run a negotiation to see the chosen plan and every check behind it.</p>
        )}
      </div>
      <LogPanel ref={traceRef} label="Run audit log" lines={run ? systemLog(run) : []} />
      {result && (
        <p className="audit">
          Export: <a href={`/runs/${result.run_id}`}>result JSON</a> ·{' '}
          <a href={`/runs/${result.run_id}/events?format=jsonl`}>events JSONL</a>
          <span className="subtle mono"> run {result.run_id.slice(0, 8)}</span>
        </p>
      )}
    </article>
  )
}

/** The decision at a glance: what happened, the plan, and what it gained over the baseline. */
function Verdict({ result, log }: { result: RunResult; log: DecisionLog }) {
  const text = STATUS_TEXT[result.status]
  const plan = result.selected_plan
  const gains = result.improvement_metrics ? improvements(result.improvement_metrics) : []
  const reason = log.decision.terminal?.reason_text
  // A known reason replaces the generic opening, so the banner states why once.
  const summary =
    result.status === 'CONSENSUS' || !reason
      ? text.summary
      : plan
        ? `${reason} Deterministic code chose a plan that passes every hard check; this is not agent consensus.`
        : `${reason} Nothing was booked.`
  return (
    <div className={`verdict verdict-${result.status.toLowerCase()}`}>
      <div className="verdict-top">
        <h3 className="verdict-status">
          {text.title}
        </h3>
        {plan && <span className="mono subtle">plan {plan.candidate_id.slice(0, 8)}</span>}
      </div>
      {plan ? (
        <p className="verdict-plan">{planHeadline(plan.action, log.decision.commit?.runway_id)}</p>
      ) : (
        <p className="verdict-plan no-plan">
          {result.status === 'ESCALATED' || result.status === 'REVIEW_REQUIRED'
            ? 'A human must decide.'
            : 'No decision was reached.'}
        </p>
      )}
      <p className="verdict-summary" aria-live="polite">
        {summary}
      </p>
      {gains.length > 0 && (
        <ul className="verdict-gains" aria-label="Versus the baseline plan">
          <li className="gain-intro">Versus baseline</li>
          {gains.map((gain) => (
            <li key={gain.label} className={`gain-${gain.tone}`}>
              <strong>{gain.text}</strong> {gain.label.toLowerCase()}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Outcome({ result, log, stale }: { result: RunResult; log: DecisionLog; stale: boolean }) {
  const stats = [
    MODE_NAMES[result.mode],
    `${result.rounds_used} ${result.rounds_used === 1 ? 'round' : 'rounds'}`,
    `${result.logical_agent_responses} agent responses`,
    `${result.provider_requests} model requests`,
    `${formatNumber(result.latency_ms / 1000, 2)} s`,
  ]
  return (
    <>
      <p className="run-stats">{stats.join(' · ')}</p>
      {stale && (
        <p className="stale" role="status">
          Inputs changed since this run. Run again to see their effect.
        </p>
      )}
      <ChosenPlan result={result} log={log} />
      <ReviewWarning result={result} />
      <h4 className="subheading">How it was decided</h4>
      <Explanation log={log} />
      {result.evaluation && <Checks checks={result.evaluation.checks} />}
      {result.review_recommendation && <Checks checks={result.review_recommendation.evaluation.checks} />}
    </>
  )
}

function ReviewWarning({ result }: { result: RunResult }) {
  const recommendation = result.review_recommendation
  if (!recommendation) return null
  const failed = recommendation.evaluation.checks.filter((check) => !check.passed)
  const action = recommendation.candidate.action
  const requiredAction = recommendation.required_action === 'AUTHORIZE' ? 'authorization' : 'remediation'
  return (
    <section className="review-warning" role="alert" aria-labelledby="review-warning-title">
      <h4 id="review-warning-title">Do not execute - human review required</h4>
      <p>
        Plan <span className="mono">{recommendation.candidate.candidate_id.slice(0, 8)}</span> at{' '}
        {clockTime(action.landing_slot)} is a non-committable recommendation. It requires human{' '}
        {requiredAction} before it can be reconsidered.
      </p>
      <ul className="rejections">
        {failed.map((check) => (
          <li key={check.constraint_id}>
            <strong className="mono">{check.constraint_id}</strong>: {formatCheckValue(check.measured, check.unit)} measured,
            {' '}limit {formatCheckValue(check.bound, check.unit)}.{' '}
            <span className="fail">{CHECK_CLASS[check.classification]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ChosenPlan({ result, log }: { result: RunResult; log: DecisionLog }) {
  const plan = result.selected_plan
  const o = result.evaluation?.outcomes
  if (!plan || !o) return null
  const a = plan.action
  return (
    <>
      <h4 className="subheading">
        {a.action === 'DIVERT' ? `Diversion to ${a.airport}` : 'Landing plan'} details
      </h4>
      <div className="final-grid">
        <DataLine label="Airport" value={a.airport} />
        <DataLine label="Runway" value={log.decision.commit?.runway_id ?? '-'} />
        <DataLine label="Touchdown" value={clockTime(o.touchdown)} note={minutesAfter(o.touchdown, log.clock)} />
        <DataLine label="At gate" value={clockTime(o.gate_arrival)} note={minutesAfter(o.gate_arrival, log.clock)} />
        <DataLine label="Gate" value={a.gate_id} />
        <DataLine label="Taxi route" value={a.taxi_path_id} note={`${formatNumber(o.taxi_min)} min`} />
        <DataLine label="Approach" value={a.approach_id} />
        <DataLine label="Crew" value={a.crew_id} />
        <DataLine label="Holding" value={`${formatNumber(o.holding_min)} min`} />
        <DataLine label="Airborne fuel" value={`${formatNumber(o.airborne_fuel_kg)} kg`} />
        <DataLine label="Landing fuel margin" value={`${formatNumber(o.landing_margin_kg)} kg`} />
        <DataLine label="Gate wait" value={`${formatNumber(o.gate_wait_min)} min`} />
        <DataLine label="Crew overtime" value={`${formatNumber(o.overtime_min)} min`} />
        <DataLine label="Missed connections" value={`${formatNumber(o.missed_connections)} pax`} />
      </div>
    </>
  )
}

function Explanation({ log }: { log: DecisionLog }) {
  const d = log.decision
  return (
    <div className="decision">
      {d.unanimous_candidates && (
        <p>
          {d.unanimous_candidates.length === 1
            ? 'One plan was accepted by all three roles.'
            : `${d.unanimous_candidates.length} plans were accepted by all three roles; the fairness rule picked the lowest worst-case domain cost.`}
        </p>
      )}
      {d.domain_costs && (
        <p className="subtle">
          Domain cost of the chosen plan:{' '}
          {ROLES.map((role) => `${ROLE_NAMES[role]} ${formatNumber(d.domain_costs![role], 2)}`).join(' · ')}
          {d.fairness_policy && ` (policy ${d.fairness_policy})`}.
        </p>
      )}
      {d.no_unanimous_plan && <p>No feasible plan was accepted by all three roles.</p>}
      {d.fallback_reason && <p>Deterministic fallback started. {d.fallback_reason}</p>}
      {d.commit && <p>Revalidated and committed {d.commit.reservations} resource reservations.</p>}
      {d.rejections && (
        <>
          <p>
            The fallback tried {formatNumber(d.rejections.plans)} plans; none passed. Most frequent failures:
          </p>
          <ul className="rejections">
            {d.rejections.most_common.map(({ constraint_id, plans }) => (
              <li key={constraint_id}>
                <span className="mono">{constraint_id}</span>{' '}
                <span className="subtle">in {formatNumber(plans)} plans</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function Checks({ checks }: { checks: CheckResult[] }) {
  const failed = checks.filter((c) => !c.passed).length
  return (
    <details className="checks">
      <summary>
        <span className="subheading">Deterministic checks for the plan</span>
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
              <th>Class</th>
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
                      <td>{CHECK_CLASS[check.classification]}</td>
                      <td>{formatCheckValue(check.measured, check.unit)}</td>
                      <td>{formatCheckValue(check.bound, check.unit)}</td>
                      <td className="num">
                        {check.margin === null ? '-' : formatCheckValue(check.margin, check.unit)}
                      </td>
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
