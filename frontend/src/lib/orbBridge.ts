/**
 * Cross-window AI-state channel (PRD §29 "floating orb").
 *
 * The main window owns the real state machine in `aiState.tsx`; the floating
 * orb window (Phase 12b) is a second webview that must show the *same* eleven
 * PRD §30 states rather than a second, drifting copy. This bridge carries the
 * owner's current state from the driving `AIStateProvider` to the mirror over
 * Tauri's event system.
 *
 * In a plain browser (no Tauri) every function here is a no-op: there is only
 * one window and the main window drives its own core directly, so nothing is
 * emitted and no subscription is opened.
 *
 * It deliberately imports only the *type* from `aiState` — a value import would
 * close a cycle (`aiState` calls `publishAIState`) and evaluate `AI_STATES`
 * before it exists. The wire guard below therefore re-lists the states; the
 * source of truth stays `AI_STATES`, and this list exists purely to reject a
 * malformed payload instead of trusting it.
 */

import { emit, listen } from '@tauri-apps/api/event'

import type { AIState } from './aiState'

/** The Tauri event that carries the owner's current `AIState`. */
const AI_STATE_EVENT = 'luxion://ai-state'

/** Tauri marks its webviews with this global; a plain browser does not. */
const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

/** Mirrors `AI_STATES` — see the module note on why it is not imported. */
const KNOWN_STATES: readonly string[] = [
  'idle',
  'listening',
  'thinking',
  'processing',
  'working',
  'speaking',
  'success',
  'warning',
  'error',
  'authenticating',
  'sleeping',
]

/** Guard a payload off the wire — never trust a mirrored value blindly. */
function isAIState(value: unknown): value is AIState {
  return typeof value === 'string' && KNOWN_STATES.includes(value)
}

/**
 * Publish the owner's current state. Called on every change by the driving
 * `AIStateProvider`; a no-op in a browser.
 */
export function publishAIState(state: AIState): void {
  if (!isTauri) return
  void emit(AI_STATE_EVENT, state)
}

/**
 * Subscribe to the owner's state. Returns a synchronous cleanup; the underlying
 * Tauri unlisten is applied as soon as it resolves — or immediately, if this
 * subscription was already torn down by then.
 */
export function onAIState(onState: (state: AIState) => void): () => void {
  if (!isTauri) return () => {}
  let disposed = false
  let unlisten: (() => void) | undefined
  void listen<unknown>(AI_STATE_EVENT, (event) => {
    if (!disposed && isAIState(event.payload)) onState(event.payload)
  }).then((fn) => {
    if (disposed) fn()
    else unlisten = fn
  })
  return () => {
    disposed = true
    unlisten?.()
  }
}
