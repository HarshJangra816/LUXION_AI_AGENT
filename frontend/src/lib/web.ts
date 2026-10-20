/**
 * Web-intelligence status + settings access.
 *
 * Powers the Settings → Web card (PRD §37/§38, Phase 9). Mirrors
 * `backend/luxion/api/routes/web.py`. The seven sources (search, weather,
 * news, movies, finance, speed, world clock) are all keyless and driven from
 * chat, not from here; the card only tunes policy and proves reachability.
 */

import { request } from './api'

/** Every knob `PUT /web/config` accepts (backend WebConfig). */
export interface WebConfig {
  enabled: boolean
  timeout_s: number
  max_results: number
  news_items: number
  search_region: string
  temperature_unit: 'celsius' | 'fahrenheit'
  wind_unit: 'kmh' | 'mph'
  speed_enabled: boolean
  speed_download_bytes: number
  speed_upload_bytes: number
  user_agent: string
}

/** Static facts about the web family (backend routes/web._status). */
export interface WebStatus {
  enabled: boolean
  speed_enabled: boolean
  /** True — every source is free/public, no API keys exist in this family. */
  keyless: boolean
  /** True — these run over plain httpx, independent of Playwright. */
  browser_independent: boolean
}

/** Enumerations the card offers as dropdowns (backend routes/web._catalog). */
export interface WebCatalog {
  news_topics: string[]
  finance_ranges: string[]
  temperature_units: string[]
  wind_units: string[]
  timezone_examples: string[]
}

/** What Settings → Web edits (effective + defaults + status + catalog). */
export interface WebConfigBundle {
  config: WebConfig
  defaults: WebConfig
  status: WebStatus
  catalog: WebCatalog
}

/** Per-source reachability from `POST /web/probe` (`ok` or `error: …`). */
export interface WebProbe {
  results: Record<string, string>
}

/** Effective web settings + source status (defaults → `.env` → web.json). */
export function getWebConfig(signal?: AbortSignal): Promise<WebConfigBundle> {
  return request<WebConfigBundle>('/web', { signal })
}

/** Persist the Settings → Web edits. */
export function setWebConfig(patch: Partial<WebConfig>): Promise<WebConfigBundle> {
  return request<WebConfigBundle>('/web/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `web.json` so `.env` / built-in defaults win again. */
export function resetWebConfig(): Promise<WebConfigBundle> {
  return request<WebConfigBundle>('/web/config', { method: 'DELETE' })
}

/** Hit every keyless source once and report which are reachable. */
export function probeWebSources(): Promise<WebProbe> {
  return request<WebProbe>('/web/probe', { method: 'POST' })
}
