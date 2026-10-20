/**
 * Email settings, probes and drafts access.
 *
 * Powers the Settings → Email card (PRD §33.4, Phase 10). Mirrors
 * `backend/luxion/api/routes/email.py`. SMTP sends + IMAP reads are stdlib
 * only; the card never carries a password — `smtp_password` does not exist in
 * any payload (the API's patch model forbids it; the secret lives in `.env`).
 */

import { request } from './api'

/** Every knob `PUT /email/config` accepts — EmailConfig minus the secret. */
export interface EmailConfig {
  enabled: boolean
  smtp_host: string
  smtp_port: number
  smtp_security: 'starttls' | 'ssl' | 'none'
  smtp_username: string
  smtp_password_env: string
  imap_host: string
  imap_port: number
  from_name: string
  from_address: string
  signature: string
  timeout_s: number
  read_limit: number
}

/** Read-only readiness facts for the card header. */
export interface EmailStatus {
  enabled: boolean
  smtp_configured: boolean
  imap_configured: boolean
  password_configured: boolean
  password_env: boolean
  from_address: string
}

/** One stored draft (never leaves the machine until an email_send_draft). */
export interface EmailDraft {
  id: string
  created_at: string
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  html: string
  attachments: string[]
}

/** Effective config + defaults + status + drafts (newest first). */
export interface EmailConfigBundle {
  config: EmailConfig
  defaults: EmailConfig
  status: EmailStatus
  drafts: EmailDraft[]
}

/** One leg's probe outcome: "ok (…)", "skipped: …" or "error: …". */
export interface EmailProbe {
  results: Record<string, string>
}

/** GET /email — effective settings plus readiness and stored drafts. */
export function getEmailConfig(signal?: AbortSignal): Promise<EmailConfigBundle> {
  return request<EmailConfigBundle>('/email', { signal })
}

/** Persist the Settings → Email edits (partial overlay, no password field). */
export function setEmailConfig(patch: Partial<EmailConfig>): Promise<EmailConfigBundle> {
  return request<EmailConfigBundle>('/email/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `email.json` so `.env` / built-in defaults win again. */
export function resetEmailConfig(): Promise<EmailConfigBundle> {
  return request<EmailConfigBundle>('/email/config', { method: 'DELETE' })
}

/** Reach SMTP and IMAP once — no mail is sent, the inbox is only selected. */
export function probeEmail(): Promise<EmailProbe> {
  return request<EmailProbe>('/email/probe', { method: 'POST' })
}

/** Remove one stored draft (404 → ApiError when it is already gone). */
export function deleteEmailDraft(id: string): Promise<{ deleted: string }> {
  return request<{ deleted: string }>(`/email/drafts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}
