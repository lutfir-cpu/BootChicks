import type { CSSProperties, ReactNode, Ref } from 'react'
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

const PACKETS = ['1', '0', '1']

/**
 * Bits that travel along one line of a connector. Every connector moves a packet in three legs, first
 * down, then across, then down again, so legs with the same packet index line up into one journey.
 */
function Bits({ leg }: { leg: 'first' | 'out-left' | 'out-right' | 'in-left' | 'in-right' | 'last' }) {
  return PACKETS.map((bit, index) => (
    <span key={index} className={`bit bit-${leg}`} style={{ '--packet': index } as CSSProperties}>
      {bit}
    </span>
  ))
}

/** One line fanning out to three; while `live`, bits flow down it into the next stage. */
export function BranchConnector({ live = false }: { live?: boolean }) {
  return (
    <div className={live ? 'branch connector is-live' : 'branch connector'} aria-hidden="true">
      <div className="stem">
        <Bits leg="first" />
      </div>
      <div className="crossbar">
        <Bits leg="out-left" />
        <Bits leg="out-right" />
      </div>
      {(['left', 'center', 'right'] as const).map((side) => (
        <div key={side} className={`drop ${side}`}>
          <Bits leg="last" />
        </div>
      ))}
    </div>
  )
}

/** Three lines joining into one; while `live`, bits flow down it into the next stage. */
export function MergeConnector({ live = false }: { live?: boolean }) {
  return (
    <div className={live ? 'merge connector is-live' : 'merge connector'} aria-hidden="true">
      {(['left', 'center', 'right'] as const).map((side) => (
        <div key={side} className={`merge-line ${side}`}>
          <Bits leg="first" />
        </div>
      ))}
      <div className="bar">
        <Bits leg="in-left" />
        <Bits leg="in-right" />
      </div>
      <div className="merge-stem">
        <Bits leg="last" />
      </div>
    </div>
  )
}
