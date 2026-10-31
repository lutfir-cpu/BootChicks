import type { CSSProperties, ReactNode, Ref } from 'react'

/** A closing cross for icon buttons, drawn to match the 1.5 px chevrons. */
export function CloseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

export function PlaneIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"
        fill="currentColor"
      />
    </svg>
  )
}
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

/** The raw event log, collapsed under the readable result; `ref` lets the top bar open and focus it. */
export function LogPanel({ label, lines, ref }: { label: string; lines: LogLine[]; ref?: Ref<HTMLDetailsElement> }) {
  if (!lines.length) return null
  return (
    <details ref={ref} className="log-panel">
      <summary>
        Log <span className="subtle">{lines.length}</span>
      </summary>
      <div className="logs" tabIndex={0} aria-label={label} role="log">
        {lines.map((entry, index) => (
          <div className="log-line" key={index}>
            <span>{entry.time}</span> {entry.message}
          </div>
        ))}
      </div>
    </details>
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
