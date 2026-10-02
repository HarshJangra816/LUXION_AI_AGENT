/**
 * Capabilities & consents (`/api/capabilities`).
 *
 * Mirrors `backend/luxion/security/capabilities.py`. These answer the hard
 * "may Luxion use this at all?" question (PRD §39) that sits *before* the
 * tool permission engine — a denied capability blocks the tool regardless
 * of autonomy level.
 */

import { request } from './api'

export type CapabilityKind = 'os' | 'app' | 'account'
export type CapabilityState =
  | 'granted'
  | 'denied'
  | 'blocked_by_os'
  | 'unavailable'
  | 'not_connected'

export interface CalendarSource {
  id: string
  kind: 'local_ics' | 'ics_subscription'
  label: string
  target: string
  writable: boolean
}

export interface CapabilityInfo {
  id: string
  label: string
  kind: CapabilityKind
  group: string
  description: string
  state: CapabilityState
  reason: string
  actions: string[]
  /** Connected sources behind an account-kind capability (calendar). */
  sources: CalendarSource[]
}

export interface CapabilityReport {
  capabilities: CapabilityInfo[]
}

export interface CapabilityActionBody {
  action: 'probe' | 'grant' | 'deny' | 'reset' | 'open_settings' | 'connect' | 'disconnect'
  /** connect: which kind of source to add. */
  source?: CalendarSource['kind']
  /** connect: filesystem path (`local_ics`) or feed URL (`ics_subscription`). */
  target?: string
  label?: string
  /** disconnect: one source id; omitted = every source. */
  id?: string
}

export const STATE_LABEL: Record<CapabilityState, string> = {
  granted: 'allowed',
  denied: 'off',
  blocked_by_os: 'blocked in windows',
  unavailable: 'unknown',
  not_connected: 'not connected',
}

export const STATE_CLASS: Record<CapabilityState, string> = {
  granted: 'border-status-ok/40 bg-status-ok/10 text-status-ok',
  denied: 'border-danger/30 bg-danger/10 text-danger',
  blocked_by_os: 'border-danger/30 bg-danger/10 text-danger',
  unavailable: 'border-warning/40 bg-warning/10 text-warning',
  not_connected: 'border-white/15 text-muted',
}

export function getCapabilities(signal?: AbortSignal): Promise<CapabilityReport> {
  return request<CapabilityReport>('/capabilities', { signal })
}

/** Run one action; the server answers with the rebuilt report. */
export function capabilityAction(
  id: string,
  body: CapabilityActionBody,
): Promise<CapabilityReport> {
  return request<CapabilityReport>(`/capabilities/${encodeURIComponent(id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
