/**
 * Desktop-notification (toast) settings access.
 *
 * Powers the Settings → Notifications card (Phase 10). Mirrors
 * `backend/luxion/api/routes/notify.py`. Toasts are raised through a
 * stdlib-only PowerShell call into the Windows WinRT toast API — the "Send
 * test" button walks exactly the same path the `notify` tool uses.
 */

import { request } from './api'

/** Every knob `PUT /notify/config` accepts (backend NotificationConfig). */
export interface NotificationConfig {
  enabled: boolean
  app_name: string
  default_duration_s: number
  sound: boolean
  cooldown_s: number
}

/** The `notifications` capability decision, as reported by the security layer. */
export interface NotifyCapability {
  state: string
  allowed: boolean
  reason: string | null
}

/** Live facts about the notification family (no subprocess, never raises). */
export interface NotifyStatus {
  enabled: boolean
  app_name: string
  sound: boolean
  cooldown_s: number
  capability: NotifyCapability
  platform: string
}

/** Effective config + defaults + status (Settings card shape). */
export interface NotifyConfigBundle {
  config: NotificationConfig
  defaults: NotificationConfig
  status: NotifyStatus
}

/** Outcome of a real test toast. */
export interface ToastOutcome {
  shown: boolean
  title: string
  duration_s: number
}

/** GET /notify — effective settings plus capability/platform status. */
export function getNotifyConfig(signal?: AbortSignal): Promise<NotifyConfigBundle> {
  return request<NotifyConfigBundle>('/notify', { signal })
}

/** Persist the Settings → Notifications edits (partial overlay). */
export function setNotifyConfig(patch: Partial<NotificationConfig>): Promise<NotifyConfigBundle> {
  return request<NotifyConfigBundle>('/notify/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `notify.json` so `.env` / built-in defaults win again. */
export function resetNotifyConfig(): Promise<NotifyConfigBundle> {
  return request<NotifyConfigBundle>('/notify/config', { method: 'DELETE' })
}

/** Raise one real toast — the honest reachability check for this family. */
export function testNotify(): Promise<ToastOutcome> {
  return request<ToastOutcome>('/notify/test', { method: 'POST' })
}
