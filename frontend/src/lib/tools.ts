/**
 * Tool catalog, permissions, audit log and confirmations (`/api/tools`).
 *
 * Mirrors `backend/luxion/api/routes/tools.py`. Three layers decide whether a
 * tool may run (PRD §21): the autonomy matrix, the guardrails, and the
 * per-tool override stored in `<data_dir>/tool_permissions.json` — the
 * override is what this module writes.
 */

import { request } from './api'

export type PermissionLevel = 'allow' | 'confirm' | 'deny'
export type ToolRisk = 'low' | 'medium' | 'high' | 'critical'
export type ToolRunStatus = 'ok' | 'error' | 'denied' | 'timeout' | 'invalid_args'

/** JSON Schema the model receives for one tool (OpenAI function shape). */
export interface ToolSchema {
  type: 'object'
  properties: Record<string, unknown>
  required?: string[]
}

export interface ToolInfo {
  name: string
  description: string
  risk: ToolRisk
  category: string
  tags: string[]
  read_only: boolean
  parameters: ToolSchema
  /** Effective decision right now (after overrides). */
  permission: PermissionLevel
  permission_reason: string
  /** What the user stored; null means "follow the autonomy default". */
  override: PermissionLevel | null
  /** Capability that must be granted before the tool may run (PRD §39). */
  requires: string | null
}

export interface RiskDefault {
  risk: ToolRisk
  level: PermissionLevel
}

export interface ToolCatalog {
  enabled: boolean
  autonomy_level: number
  tools: ToolInfo[]
  defaults: RiskDefault[]
}

export interface PermissionReport {
  overrides: Record<string, PermissionLevel>
  defaults: RiskDefault[]
}

export interface ToolLogEntry {
  timestamp: string
  tool: string
  target: string | null
  risk: ToolRisk
  permission: string
  result: 'success' | 'error' | 'denied' | 'timeout' | 'invalid_args'
  duration_ms: number | null
  conversation_id: string | null
  args: Record<string, unknown>
  output: string | null
  error: string | null
}

export interface ToolLogResponse {
  entries: ToolLogEntry[]
}

export interface PendingConfirmation {
  id: string
  tool: string
  risk: ToolRisk
  args: Record<string, unknown>
  reason: string
  description: string
  conversation_id: string | null
  age_s: number
}

export interface ConfirmationList {
  confirmations: PendingConfirmation[]
  timeout_s: number
}

export interface ToolRunResult {
  tool: string
  status: ToolRunStatus
  output: string
  error: string | null
  duration_ms: number | null
  args: Record<string, unknown>
  risk: ToolRisk
  permission: PermissionLevel | 'n/a'
  permission_reason: string
}

const jsonBody = (payload: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export function getToolCatalog(signal?: AbortSignal): Promise<ToolCatalog> {
  return request<ToolCatalog>('/tools', { signal })
}

/** Preview of what the model would be offered for a trial query (PRD §19). */
export function getExposedTools(query: string, signal?: AbortSignal): Promise<string[]> {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : ''
  return request<string[]>(`/tools/exposed${suffix}`, { signal })
}

export function getPermissions(signal?: AbortSignal): Promise<PermissionReport> {
  return request<PermissionReport>('/tools/permissions', { signal })
}

/** Set (or with `null`, clear) one override — also accepts `category:<name>`. */
export function setPermission(
  name: string,
  level: PermissionLevel | null,
): Promise<PermissionReport> {
  return request<PermissionReport>(`/tools/permissions/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  })
}

export function clearPermissions(): Promise<PermissionReport> {
  return request<PermissionReport>('/tools/permissions', { method: 'DELETE' })
}

export function getToolLog(limit = 50, signal?: AbortSignal): Promise<ToolLogResponse> {
  return request<ToolLogResponse>(`/tools/log?limit=${limit}`, { signal })
}

export function getConfirmations(signal?: AbortSignal): Promise<ConfirmationList> {
  return request<ConfirmationList>('/tools/confirmations', { signal })
}

/** Answer a prompt raised mid-turn; throws 404 when it is already resolved. */
export function resolveConfirmation(id: string, approved: boolean): Promise<{ resolved: boolean }> {
  return request<{ resolved: boolean }>(
    `/tools/confirmations/${encodeURIComponent(id)}`,
    jsonBody({ approved }),
  )
}

export function runTool(
  name: string,
  args: Record<string, unknown>,
  approved = false,
): Promise<ToolRunResult> {
  return request<ToolRunResult>(`/tools/${encodeURIComponent(name)}/run`, jsonBody({ args, approved }))
}
