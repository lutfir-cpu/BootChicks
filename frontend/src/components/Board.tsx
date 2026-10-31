import { actionText, clockTime } from '../labels'
import { boardStatus, skippedReason, type RunView } from '../trace'
import { Loading, RoleTag, StatusBadge } from './Layout'

export function ProposalBoard({ run }: { run: RunView | null }) {
  const status = boardStatus(run)
  const board = run?.log.board?.candidates
  const selected = run?.result?.selected_plan?.plan_hash ?? null
  const feasible = board?.filter((e) => e.feasible).length ?? 0
  return (
    <article className="card wide-card" aria-labelledby="board-title">
      <div className="agent-head">
        <h3 id="board-title">Proposal board</h3>
        <StatusBadge
          status={board && feasible === 0 ? 'error' : status}
          label={board ? `${feasible} of ${board.length} feasible` : undefined}
        />
      </div>
      {board ? (
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
              {board.map((c) => {
                const failed = c.checks.filter((check) => !check.passed)
                return (
                  <tr key={c.plan_hash} className={c.plan_hash === selected ? 'selected' : undefined}>
                    <td className="mono" title={actionText(c.action)}>
                      {c.candidate_id.slice(0, 8)}
                    </td>
                    <td>
                      {clockTime(c.action.landing_slot)} {c.action.runway_id}
                    </td>
                    <td>{c.action.gate_id}</td>
                    <td>
                      <span className="roles">
                        {c.proposers.map((role) => (
                          <RoleTag key={role} role={role} />
                        ))}
                      </span>
                    </td>
                    <td>
                      {failed.length === 0 ? (
                        <span className="pass">All {c.checks.length} pass</span>
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
      ) : (
        <div className="agent-body">
          {status === 'running' && <Loading>Checking every proposal...</Loading>}
          {status === 'waiting' && <p className="empty-value">Every proposed plan is checked here.</p>}
          {status === 'skipped' && run && <p className="empty-value">{skippedReason(run)}</p>}
        </div>
      )}
    </article>
  )
}
