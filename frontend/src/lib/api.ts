/**
 * Backend API access.
 *
 * In `npm run dev` the request goes through the Vite proxy (`/api`), inside
 * the Tauri webview it goes straight to the local backend.
 */

export interface HealthPayload {
  status: 'ok' | 'degraded'
  service: string
  version: string
  api_version: string
  time_utc: string
  uptime_s: number
  database: string
}

export interface VersionPayload {
  name: string
  version: string
  api_version: string
}

/** Result of the background `/api/health` probe. */
export type BackendState =
  | { kind: 'connecting' }
  | { kind: 'online'; health: HealthPayload }
  | { kind: 'offline'; error: string }

/** Short human label for the sidebar/status chip. */
export function statusLabel(state: BackendState): string {
  if (state.kind === 'online') return 'Backend connected'
  if (state.kind === 'offline') return 'Backend offline'
  return 'Connecting…'
}

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export const API_BASE = isTauri ? 'http://127.0.0.1:8756/api' : '/api'

/** HTTP error carrying the backend's `detail` message. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Turn a failed response into an `ApiError` carrying the backend's detail. */
export async function errorFrom(response: Response): Promise<ApiError> {
  let detail = `HTTP ${response.status}`
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail)) detail = 'Request validation failed'
  } catch {
    // non-JSON error body; keep the status text
  }
  return new ApiError(response.status, detail)
}

/** GET (or `init`-driven) JSON request that throws `ApiError` on failure. */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) throw await errorFrom(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthPayload> {
  const response = await fetch(`${API_BASE}/health`, { signal })
  if (!response.ok) {
    throw new Error(`health check failed: HTTP ${response.status}`)
  }
  return (await response.json()) as HealthPayload
}

export async function fetchVersion(signal?: AbortSignal): Promise<VersionPayload> {
  const response = await fetch(`${API_BASE}/version`, { signal })
  if (!response.ok) {
    throw new Error(`version check failed: HTTP ${response.status}`)
  }
  return (await response.json()) as VersionPayload
}
