/**
 * Coding-agent status + settings access.
 *
 * Powers the Settings → Coding card (PRD §32/§34, Phase 8). Mirrors
 * `backend/luxion/api/routes/code.py`; the coding agent is driven by the
 * `analyze_project` / `grep_code` / `edit_file` / `run_*` / `git_*` tools
 * in chat, not from here.
 */

import { request } from './api'

/** Capability states the backend reports for `terminal`. */
export type CapabilityState =
  | 'granted'
  | 'denied'
  | 'blocked_by_os'
  | 'unavailable'
  | 'not_connected'

/** Every knob `PUT /code/config` accepts (backend CodeConfig). */
export interface CodeConfig {
  enabled: boolean
  command_timeout_s: number
  max_output_chars: number
}

/** Live facts about this machine (backend routes/code._status). */
export interface CodeStatus {
  platform: string
  /** False when git is not on PATH — the git tools answer clearly. */
  git: boolean
  /** False when the GitHub CLI is missing — github_prs says so. */
  github_cli: boolean
  /** The directory the coding tools treat as the project root. */
  workspace: string | null
  /** Whether the model may run commands on this machine at all. */
  terminal_capability: CapabilityState
  terminal_capability_reason: string | null
  enabled: boolean
}

/** What Settings → Coding edits (effective + defaults + status). */
export interface CodeConfigBundle {
  config: CodeConfig
  defaults: CodeConfig
  status: CodeStatus
}

/** Effective coding settings + toolchain status (defaults → `.env` → code.json). */
export function getCodeConfig(signal?: AbortSignal): Promise<CodeConfigBundle> {
  return request<CodeConfigBundle>('/code', { signal })
}

/** Persist the Settings → Coding edits. */
export function setCodeConfig(patch: Partial<CodeConfig>): Promise<CodeConfigBundle> {
  return request<CodeConfigBundle>('/code/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `code.json` so `.env` / built-in defaults win again. */
export function resetCodeConfig(): Promise<CodeConfigBundle> {
  return request<CodeConfigBundle>('/code/config', { method: 'DELETE' })
}
