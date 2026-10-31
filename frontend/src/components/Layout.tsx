import { useEffect, useState, type CSSProperties, type ReactNode, type Ref } from 'react'
import bootchickLogo from '../assets/images/bootchick.jpg'
import { ROLE_NAMES } from '../labels'
import type { CardStatus, LogLine } from '../trace'
import type { Role } from '../types'

/** A closing cross for icon buttons, drawn to match the 1.5 px chevrons. */
export function CloseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

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

const LOADING_LINES = [
  'Hatching data, hold your feathers.',
  'Taxiing files to the runway.',
  'Pre-flight checks in progress now.',
  'Ground control syncing your load.',
  'Clearing airspace for your files.',
  'Engines spooling up, almost ready.',
  'Roosting data into position now.',
]

const LOADING_LINE_MS = 2500

/**
 * A pulsing chick beside a rotating line; `icon` swaps the BootChicks logo for another image (or `null` when
 * the caller shows its own), and `offset` staggers the starting line so side-by-side loaders differ.
 */
export function Loading({ icon = bootchickLogo, offset = 0 }: { icon?: string | null; offset?: number }) {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick((value) => value + 1), LOADING_LINE_MS)
    return () => clearInterval(timer)
  }, [])
  return (
    <p className="loading">
      {icon && <img className="loading-chick" src={icon} alt="" aria-hidden="true" />} {LOADING_LINES[(offset + tick) % LOADING_LINES.length]}
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
