import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { keyframes, runAt, type RunView, type Stage } from './trace'

/** One replay step; agents replying in turn pause one step, stage changes two. */
export const STEP_MS = 400

/**
 * Replays a run one step at a time, so each step stays on screen for its minimum time even when the
 * backend finishes in milliseconds. Steps that arrive slower than that, as in live runs, show at once.
 */
export function usePlayback(run: RunView | null, stepMs: number) {
  const runId = run?.log.run_id ?? null
  const [shown, setShown] = useState({ runId, sequence: -Infinity })
  const shownAt = useRef(0)
  if (shown.runId !== runId) setShown({ runId, sequence: -Infinity })
  const sequence = shown.runId === runId ? shown.sequence : -Infinity

  const next = useMemo(() => (run ? keyframes(run) : []).find((f) => f.sequence > sequence), [run, sequence])
  const nextSequence = next?.sequence
  const wait = (next?.steps ?? 0) * stepMs

  useEffect(() => {
    shownAt.current = Date.now()
  }, [runId])

  useEffect(() => {
    if (runId === null || nextSequence === undefined) return
    const timer = setTimeout(
      () => {
        shownAt.current = Date.now()
        setShown({ runId, sequence: nextSequence })
      },
      Math.max(0, shownAt.current + wait - Date.now()),
    )
    return () => clearTimeout(timer)
  }, [runId, nextSequence, wait])

  const view = useMemo(() => (run && sequence > -Infinity ? runAt(run, sequence) : null), [run, sequence])
  return {
    view,
    replaying: nextSequence !== undefined,
    skip: () => setShown({ runId, sequence: Infinity }),
  }
}

const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '])

/**
 * While `following`, keep the active stage in view. Scrolling by hand stops following until the next run;
 * so does the run settling, once its last stage is in view.
 */
export function useFollowStage(
  sections: RefObject<Partial<Record<Stage, HTMLElement | null>>>,
  stage: Stage | null,
  following: boolean,
  settled: boolean,
  stop: () => void,
) {
  useEffect(() => {
    if (!following) return
    const onKey = (event: KeyboardEvent) => {
      const editing = event.target instanceof Element && event.target.closest('input, textarea, select')
      if (SCROLL_KEYS.has(event.key) && !editing) stop()
    }
    window.addEventListener('wheel', stop, { passive: true })
    window.addEventListener('touchmove', stop, { passive: true })
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('wheel', stop)
      window.removeEventListener('touchmove', stop)
      window.removeEventListener('keydown', onKey)
    }
  }, [following, stop])

  useEffect(() => {
    if (!following) return
    const section = stage && sections.current[stage]
    if (section) {
      const fits = section.getBoundingClientRect().height < window.innerHeight * 0.8
      const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
      section.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: fits ? 'center' : 'start' })
    }
    if (settled) stop()
  }, [sections, stage, following, settled, stop])
}
