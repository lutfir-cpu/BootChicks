import type { DecisionLog, Options, RunRequest, RunResult, RunState } from './types'

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

function fetchRun(runId: string): Promise<RunState> {
  return request(`/runs/${runId}`)
}

function fetchDecisions(runId: string): Promise<DecisionLog> {
  return request(`/runs/${runId}/decisions`)
}

/**
 * Poll a run's decision log until it finishes, reporting each agent's decisions as they are recorded,
 * then read the final result. Live runs take up to their 150 s total budget.
 */
export async function followRun(
  runId: string,
  onProgress: (log: DecisionLog) => void,
  { intervalMs = 400, timeoutMs = 180_000 } = {},
): Promise<{ result: RunResult; log: DecisionLog }> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const log = await fetchDecisions(runId)
    if (log.finished) {
      const { result } = await fetchRun(runId)
      if (!result) throw new ApiError('The run finished without a result.')
      return { result, log }
    }
    onProgress(log)
    if (Date.now() > deadline) throw new ApiError('The run did not finish within 3 minutes.')
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}
