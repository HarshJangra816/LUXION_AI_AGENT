/**
 * WhatsApp automation settings + session access.
 *
 * Powers the Settings → WhatsApp card (PRD §33.3, Phase 10). Mirrors
 * `backend/luxion/api/routes/whatsapp.py`. The session runs Playwright Web on
 * web.whatsapp.com with a persistent profile; login is a QR scan. The card
 * only manages session lifecycle and policy — it never types into a chat.
 */

import { request } from './api'

/** Every knob `PUT /whatsapp/config` accepts (backend WhatsAppConfig). */
export interface WhatsAppConfig {
  enabled: boolean
  headless: boolean
  profile_dir: string
  timeout_s: number
  login_timeout_s: number
}

/** Live facts about the automation session. */
export interface WhatsAppStatus {
  enabled: boolean
  running: boolean
  headless: boolean
  logged_in: boolean | null
  url: string | null
  profile_dir: string
  timeout_s: number
  login_timeout_s: number
}

/** Effective config + defaults + status (Settings card shape). */
export interface WhatsAppConfigBundle {
  config: WhatsAppConfig
  defaults: WhatsAppConfig
  status: WhatsAppStatus
}

/** Session lifecycle result: `qr` is a PNG data-URL while waiting for a scan. */
export interface WhatsAppSession {
  running: boolean
  logged_in: boolean | null
  qr: string | null
  url: string | null
}

/** GET /whatsapp — effective settings plus session status. */
export function getWhatsAppConfig(signal?: AbortSignal): Promise<WhatsAppConfigBundle> {
  return request<WhatsAppConfigBundle>('/whatsapp', { signal })
}

/** Persist the Settings → WhatsApp edits (partial overlay). */
export function setWhatsAppConfig(patch: Partial<WhatsAppConfig>): Promise<WhatsAppConfigBundle> {
  return request<WhatsAppConfigBundle>('/whatsapp/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `whatsapp.json` so `.env` / built-in defaults win again. */
export function resetWhatsAppConfig(): Promise<WhatsAppConfigBundle> {
  return request<WhatsAppConfigBundle>('/whatsapp/config', { method: 'DELETE' })
}

/** Launch the persistent session; returns the QR while logged out. */
export function openWhatsAppSession(): Promise<WhatsAppSession> {
  return request<WhatsAppSession>('/whatsapp/session', { method: 'POST' })
}

/** Re-check the live session for login (poll after scanning the QR). */
export function getWhatsAppSession(): Promise<WhatsAppSession> {
  return request<WhatsAppSession>('/whatsapp/status', { method: 'POST' })
}

/** Tear the session down (the profile keeps the login for next time). */
export function closeWhatsAppSession(): Promise<{ running: boolean }> {
  return request<{ running: boolean }>('/whatsapp/close', { method: 'POST' })
}
