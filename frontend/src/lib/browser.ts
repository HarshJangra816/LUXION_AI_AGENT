/**
 * Browser agent status + settings access.
 *
 * Powers the Settings → Browser card (PRD §32/§5.7, Phase 6). Mirrors
 * `backend/luxion/api/routes/browser.py`; the browser is driven by the
 * `browser_*` / `youtube_*` tools in chat, not from here.
 */

import { request } from './api'

/** Search engines `browser_search` knows (backend SEARCH_URLS). */
export const SEARCH_ENGINES = ['duckduckgo', 'google', 'bing'] as const
export type SearchEngine = (typeof SEARCH_ENGINES)[number]

/** Every knob `PUT /browser/config` accepts (backend BrowserConfig). */
export interface BrowserConfig {
  enabled: boolean
  headless: boolean
  search_engine: SearchEngine
  navigation_timeout_s: number
  action_timeout_s: number
  extract_max_chars: number
  user_agent: string
  download_dir: string | null
}

/** Live facts about the Playwright session (backend manager.status()). */
export interface BrowserStatus {
  enabled: boolean
  running: boolean
  headless: boolean
  search_engine: SearchEngine
  navigation_timeout_s: number
  action_timeout_s: number
  extract_max_chars: number
  /** Current page URL while a session is open. */
  url: string | null
  download_dir: string
}

/** What Settings → Browser edits (effective + defaults + status). */
export interface BrowserConfigBundle {
  config: BrowserConfig
  defaults: BrowserConfig
  status: BrowserStatus
}

/** Effective browser settings + session status (defaults → `.env` → browser.json). */
export function getBrowserConfig(signal?: AbortSignal): Promise<BrowserConfigBundle> {
  return request<BrowserConfigBundle>('/browser', { signal })
}

/** Persist the Settings → Browser edits. */
export function setBrowserConfig(
  patch: Partial<BrowserConfig>,
): Promise<BrowserConfigBundle> {
  return request<BrowserConfigBundle>('/browser/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `browser.json` so `.env` / built-in defaults win again. */
export function resetBrowserConfig(): Promise<BrowserConfigBundle> {
  return request<BrowserConfigBundle>('/browser/config', { method: 'DELETE' })
}
