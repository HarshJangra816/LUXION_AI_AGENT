/**
 * Voice + face second-factor access (PRD §27/§28, Phase 11c).
 *
 * Powers the Settings → Authentication card. Mirrors
 * `backend/luxion/api/routes/auth.py`. Two local biometric paths behind one
 * contract — *who is speaking* and *who is on camera* — neither of which
 * leaves the box. This is deliberately **not** speech recognition: speech
 * recognition answers *what was said*, this answers *who said it*.
 */

import { request } from './api'

/** PRD §28's four-state security configuration. */
export type AuthMode = 'disabled' | 'voice_only' | 'face_only' | 'voice_face'

/** Which second factors a profile belongs to. */
export type Modality = 'voice' | 'face'

/** Every knob `PUT /auth/config` accepts (backend BiometricsConfig). */
export interface AuthConfig {
  mode: AuthMode
  voice_duration_s: number
  voice_threshold: number
  face_threshold: number
  max_profiles: number
}

/** A resolved capability decision (backend CapabilityDecision). */
export interface CapabilityDecision {
  capability: string
  state: string
  allowed: boolean
  reason: string
}

/** Static + live facts about the auth family (backend routes/auth.auth_status). */
export interface AuthStatus {
  mode: AuthMode
  max_profiles: number
  biometrics: CapabilityDecision
  microphone: CapabilityDecision
  camera: CapabilityDecision
  /** OpenCV importable (import check only — never opens the camera). */
  opencv_available: boolean
  /** Both face networks present in this OpenCV build. */
  face_api: boolean
  /** Per-model presence (downloaded once on first use, never on load). */
  models: Record<string, boolean>
  models_ready: boolean
  /** Enrolled profile count per modality. */
  profiles: Record<Modality, number>
}

/** Enumerations + limits the card offers as hints (backend routes/auth._catalog). */
export interface AuthCatalog {
  modes: Array<{ value: AuthMode; label: string }>
  modalities: Modality[]
  max_profiles: number
  duration_range: [number, number]
  threshold_range: [number, number]
  models: Array<{ id: string; filename: string; url: string }>
}

/** What Settings → Authentication edits (effective + defaults + status + catalog). */
export interface AuthConfigBundle {
  config: AuthConfig
  defaults: AuthConfig
  status: AuthStatus
  catalog: AuthCatalog
}

/** One enrolled profile (backend ProfileStore entry). */
export interface AuthProfile {
  name: string
  samples?: number
  enrolled_at?: string
  source?: string
  duration_s?: number
  frames?: number
  rate?: number
  detection_score?: number
}

/** Every enrolled profile, grouped by modality (`GET /auth/profiles`). */
export interface AuthProfiles {
  voice: AuthProfile[]
  face: AuthProfile[]
}

/** One enrollment or verification result (`POST /auth/enroll` / `/verify`). */
export interface AuthOutcome {
  modality: Modality
  message: string
  // enrollment
  name?: string
  slug?: string
  enrolled_at?: string
  profiles?: number
  frames?: number
  duration_s?: number
  // verification
  matched?: boolean
  score?: number
  threshold?: number
  profile?: string | null
  candidates?: Array<{ name: string; slug: string; score: number }>
  // both
  source?: string
  detection_score?: number
  elapsed_ms: number
}

/** Effective auth settings + status (defaults → `.env` → biometrics.json). */
export function getAuthConfig(signal?: AbortSignal): Promise<AuthConfigBundle> {
  return request<AuthConfigBundle>('/auth', { signal })
}

/** Persist the Settings → Authentication edits. */
export function setAuthConfig(patch: Partial<AuthConfig>): Promise<AuthConfigBundle> {
  return request<AuthConfigBundle>('/auth/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `biometrics.json` so `.env` / built-in defaults win again. */
export function resetAuthConfig(): Promise<AuthConfigBundle> {
  return request<AuthConfigBundle>('/auth/config', { method: 'DELETE' })
}

/** Every enrolled voice/face profile. */
export function listAuthProfiles(signal?: AbortSignal): Promise<AuthProfiles> {
  return request<AuthProfiles>('/auth/profiles', { signal })
}

/** Forget one profile (PRD §27 "configured" implies it can be un-configured). */
export function deleteAuthProfile(
  modality: Modality,
  name: string,
): Promise<{ modality: Modality; name: string; deleted: boolean }> {
  return request(`/auth/profiles/${encodeURIComponent(modality)}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
}

/** Capture a clip/frame and store it as a profile. */
export function enrollAuth(payload: {
  modality: Modality
  name: string
  path?: string
  duration_s?: number
}): Promise<AuthOutcome> {
  return request<AuthOutcome>('/auth/enroll', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Score a fresh clip/frame against the stored profiles. */
export function verifyAuth(payload: {
  modality: Modality
  name?: string
  path?: string
  duration_s?: number
}): Promise<AuthOutcome> {
  return request<AuthOutcome>('/auth/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
