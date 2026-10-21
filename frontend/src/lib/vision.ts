/**
 * Vision status + settings access.
 *
 * Powers the Settings → Vision card (PRD §5.9/§33.15, Phase 11). Mirrors
 * `backend/luxion/api/routes/vision.py`. The vision tools (`analyze_image`,
 * `analyze_screenshot`) run from chat; the card only tunes policy, points
 * Luxion at a vision model and proves the setup really works.
 */

import { request } from './api'

/** Every knob `PUT /vision/config` accepts (backend VisionConfig). */
export interface VisionConfig {
  enabled: boolean
  model: string
  provider: string
  base_url: string
  api_key_env: string
  prompt: string
  max_images: number
  max_dimension: number
  max_bytes: number
  timeout_s: number
}

/** Static facts about the vision family (backend routes/vision._status). */
export interface VisionStatus {
  enabled: boolean
  /** True — the vision call reuses the chat provider, so no new key. */
  keyless: boolean
  /** True — no browser and no extra Python dependency for the model call. */
  browser_independent: boolean
  /** True — the vision model runs on the chat adapter's endpoint. */
  uses_chat_provider: boolean
}

/** Enumerations the card offers as hints (backend routes/vision._catalog). */
export interface VisionCatalog {
  suggested_models: string[]
  supported_types: string[]
  max_images: number
}

/** What Settings → Vision edits (effective + defaults + status + catalog). */
export interface VisionConfigBundle {
  config: VisionConfig
  defaults: VisionConfig
  status: VisionStatus
  catalog: VisionCatalog
}

/** Reachability of the vision endpoint (`POST /vision/probe`). */
export interface VisionProbe {
  ok: boolean
  provider: string
  model: string
  models: string[]
  found: boolean
  error: string | null
}

/** The answer to one analysis (`POST /vision/analyze`). */
export interface VisionAnalysis {
  answer: string
  path: string | null
  image: {
    source: string
    mime: string
    width: number
    height: number
    bytes: number
  }
}

/** Effective vision settings + endpoint status (defaults → `.env` → vision.json). */
export function getVisionConfig(signal?: AbortSignal): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision', { signal })
}

/** Persist the Settings → Vision edits. */
export function setVisionConfig(patch: Partial<VisionConfig>): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `vision.json` so `.env` / built-in defaults win again. */
export function resetVisionConfig(): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision/config', { method: 'DELETE' })
}

/** Check that the vision endpoint is reachable and knows the model. */
export function probeVision(): Promise<VisionProbe> {
  return request<VisionProbe>('/vision/probe', { method: 'POST' })
}

/** Look at an image file (or the screen) and return the model's answer. */
export function analyzeImage(payload: {
  path?: string
  screenshot?: boolean
  question?: string
}): Promise<VisionAnalysis> {
  return request<VisionAnalysis>('/vision/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
