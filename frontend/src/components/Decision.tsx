import { Fragment, type Ref } from 'react'
import {
  clockTime,
  formatCheckValue,
  formatNumber,
  improvements,
  minutesAfter,
  MODE_NAMES,
  ROLE_NAMES,
  STATUS_TEXT,
} from '../labels'
import { systemLog, type RunView } from '../trace'
import { ROLES, type CheckResult, type DecisionLog, type RunResult } from '../types'
import { DataLine, Loading, LogPanel, RoleTag, StatusBadge } from './Layout'

export function DecisionCard({
  run,
  stale,
  traceRef,
}: {
  run: RunView | null
  stale: boolean
  traceRef: Ref<HTMLDivElement>
}) {
  const result = run?.result
  return (
    <article className="card wide-card" aria-labelledby="decision-title">
      <div className="agent-head">
        <h3 id="decision-title">Decision</h3>
        {result ? (
          <span className={`badge badge-outcome-${result.status.toLowerCase()}`}>{STATUS_TEXT[result.status].title}</span>
        ) : (
          <StatusBadge status={run ? 'running' : 'waiting'} />
        )}
      </div>
      <LogPanel ref={traceRef} label="Run audit log" lines={run ? systemLog(run) : []} />
      <div className="output">
        {result && run ? (
          <Outcome result={result} log={run.log} stale={stale} />
        ) : run ? (
          <Loading>Waiting for the agents and checks...</Loading>
        ) : (
          <p className="empty-value">Waiting.</p>
        )}
      </div>
    </article>
  )
}

function Outcome({ result, log, stale }: { result: RunResult; log: DecisionLog; stale: boolean }) {
  const text = STATUS_TEXT[result.status]
  return (
    <>
      <h4 className="panel-title">Outcome</h4>
      <p className="outcome-summary" aria-live="polite">
        {text.summary}
        {result.status !== 'CONSENSUS' && log.decision.terminal && ` ${log.decision.terminal.reason_text}`}
      </p>
      {stale && (
        <p className="stale" role="status">
          Inputs changed since this run. Run again to see their effect.
        </p>
      )}
      <div className="final-grid">
        <DataLine label="Agents" value={MODE_NAMES[result.mode]} />
        <DataLine label="Rounds" value={String(result.rounds_used)} />
        <DataLine label="Agent responses" value={String(result.logical_agent_responses)} />
        <DataLine label="Model requests" value={String(result.provider_requests)} />
        <DataLine label="Time" value={`${formatNumber(result.latency_ms / 1000, 2)} s`} />
      </div>
      <ChosenPlan result={result} log={log} />
      <h4 className="subheading">How it was decided</h4>
      <Explanation log={log} />
      {result.evaluation && <Checks checks={result.evaluation.checks} />}
      <p className="audit">
        Audit trail: <a href={`/runs/${result.run_id}`}>result JSON</a> ·{' '}
        <a href={`/runs/${result.run_id}/events?format=jsonl`}>events JSONL</a>
        <span className="subtle mono"> run {result.run_id.slice(0, 8)}</span>
      </p>
    </>
  )
}

function ChosenPlan({ result, log }: { result: RunResult; log: DecisionLog }) {
  const plan = result.selected_plan
  const o = result.evaluation?.outcomes
  if (!plan || !o) return null
  const a = plan.action
  const gains = result.improvement_metrics ? improvements(result.improvement_metrics) : []
  return (
    <>
      <h4 className="subheading">
        {a.action === 'DIVERT' ? `Diversion to ${a.airport}` : 'Landing plan'}
        <span className="mono subtle"> {plan.candidate_id.slice(0, 8)}</span>
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
      {gains.length > 0 && (
        <>
          <h4 className="subheading">Compared with the baseline plan</h4>
          <div className="final-grid">
            {gains.map((gain) => (
              <DataLine key={gain.label} label={gain.label} value={gain.text} tone={gain.tone} />
            ))}
          </div>
        </>
      )}
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
        <span className="subheading">Hard checks for the chosen plan</span>
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
