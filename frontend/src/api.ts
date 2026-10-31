import type { AuditEvent, Options, RunRequest, RunState } from './types'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('Cannot reach the BootChicks server. Start it with "bootchicks serve".')
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response))
  }
  return (await response.json()) as T
}

/** FastAPI reports either a string detail or a list of validation errors. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: string }
      if (first.msg) return first.msg.replace(/^Value error, /, '')
    }
  } catch {
    // Fall through to the status line.
  }
  return `Server returned ${response.status} ${response.statusText}.`.trim()
}

export function fetchOptions(): Promise<Options> {
  return request('/options')
}

export function startRun(body: RunRequest, idempotencyKey: string): Promise<{ run_id: string }> {
  return request('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(body),
  })
}

export function fetchRun(runId: string): Promise<RunState> {
  return request(`/runs/${runId}`)
}

export function fetchEvents(runId: string): Promise<AuditEvent[]> {
  return request(`/runs/${runId}/events`)
}

const TERMINAL = new Set(['CONSENSUS', 'FALLBACK', 'ESCALATED', 'FAILED'])

/** Poll until the run reaches a terminal status. Live runs take up to the 30 s total budget. */
export async function waitForRun(
  runId: string,
  { intervalMs = 400, timeoutMs = 60_000 } = {},
): Promise<RunState> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const state = await fetchRun(runId)
    if (TERMINAL.has(state.status)) return state
    if (Date.now() > deadline) throw new ApiError('The run did not finish within 60 seconds.')
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}
