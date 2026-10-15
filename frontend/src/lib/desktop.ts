/**
 * Desktop automation status + settings access.
 *
 * Powers the Settings → Desktop card (PRD §32/§5.8, Phase 7). Mirrors
 * `backend/luxion/api/routes/desktop.py`; the desktop is driven by the
 * `list_*` / `inspect_*` / `press_keys` / `type_text` / `click_*` /
 * `control_*` tools in chat, not from here.
 */

import { request } from './api'

/** Capability states the backend reports for `input_control`. */
export type CapabilityState =
  | 'granted'
  | 'denied'
  | 'blocked_by_os'
  | 'unavailable'
  | 'not_connected'

/** Every knob `PUT /desktop/config` accepts (backend DesktopConfig). */
export interface DesktopConfig {
  enabled: boolean
  ui_automation: boolean
  coordinate_fallback: boolean
  max_elements: number
  max_processes: number
  focus_delay_s: number
}

/** Live facts about this machine (backend routes/desktop._status). */
export interface DesktopStatus {
  /** False on macOS/Linux — the desktop tools answer "unsupported". */
  supported: boolean
  platform: string
  /** False when pywinauto is missing, so only focus + coordinates remain. */
  ui_automation: boolean
  /** How many visible windows this machine has right now. */
  windows: number
  /** Whether the model may inject keyboard/mouse input at all. */
  input_capability: CapabilityState
  input_capability_reason: string | null
  enabled: boolean
}

/** What Settings → Desktop edits (effective + defaults + status). */
export interface DesktopConfigBundle {
  config: DesktopConfig
  defaults: DesktopConfig
  status: DesktopStatus
}

/** Effective desktop settings + platform status (defaults → `.env` → desktop.json). */
export function getDesktopConfig(signal?: AbortSignal): Promise<DesktopConfigBundle> {
  return request<DesktopConfigBundle>('/desktop', { signal })
}

/** Persist the Settings → Desktop edits. */
export function setDesktopConfig(
  patch: Partial<DesktopConfig>,
): Promise<DesktopConfigBundle> {
  return request<DesktopConfigBundle>('/desktop/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `desktop.json` so `.env` / built-in defaults win again. */
export function resetDesktopConfig(): Promise<DesktopConfigBundle> {
  return request<DesktopConfigBundle>('/desktop/config', { method: 'DELETE' })
}
