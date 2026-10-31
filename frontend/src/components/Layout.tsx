import type { ReactNode, Ref } from 'react'
import { ROLE_NAMES } from '../labels'
import type { CardStatus, LogLine } from '../trace'
import type { Role } from '../types'

const STATUS_LABELS: Record<CardStatus, string> = {
  waiting: 'Waiting',
  running: 'Running',
  complete: 'Complete',
  error: 'No reply',
  skipped: 'Skipped',
}

export function StatusBadge({ status, label }: { status: CardStatus; label?: string }) {
  return <span className={`badge badge-${status}`}>{label ?? STATUS_LABELS[status]}</span>
}

export function RoleTag({ role }: { role: Role }) {
  return <span className={`role role-${role.toLowerCase()}`}>{ROLE_NAMES[role]}</span>
}

export function LogPanel({ label, lines, ref }: { label: string; lines: LogLine[]; ref?: Ref<HTMLDivElement> }) {
  return (
    <div className="panel-block">
      <h4 className="panel-title">Logs</h4>
      <div ref={ref} className="logs" tabIndex={0} aria-label={label} role="log">
        {lines.length ? (
          lines.map((entry, index) => (
            <div className="log-line" key={index}>
              <span>[{entry.time}]</span> {entry.message}
            </div>
          ))
        ) : (
          <span className="empty-value">No entries yet.</span>
        )}
      </div>
    </div>
  )
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="output">
      <h4 className="panel-title">{title}</h4>
      {children}
    </div>
  )
}

export function Loading({ children }: { children: ReactNode }) {
  return (
    <p className="loading">
      <span className="spinner" aria-hidden="true" /> {children}
    </p>
  )
}

export function DataLine({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: ReactNode
  note?: string
  tone?: 'better' | 'worse' | 'same'
}) {
  return (
    <div className="data-line">
      <span>{label}</span>
      <span className={tone ? `tone-${tone}` : undefined}>
        {value}
        {note && <span className="subtle"> {note}</span>}
      </span>
    </div>
  )
}

export function BranchConnector() {
  return (
    <div className="branch connector" aria-hidden="true">
      <div className="stem" />
      <div className="crossbar" />
      <div className="drop left" />
      <div className="drop center" />
      <div className="drop right" />
    </div>
  )
}

export function MergeConnector() {
  return (
    <div className="merge connector" aria-hidden="true">
      <div className="merge-line left" />
      <div className="merge-line center" />
      <div className="merge-line right" />
      <div className="bar" />
      <div className="merge-stem" />
    </div>
  )
}
