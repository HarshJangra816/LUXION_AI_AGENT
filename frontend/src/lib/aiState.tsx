/**
 * AI core state — drives the 3D scene's reactivity and the status HUD.
 *
 * All eleven PRD §30 states are here. They are never faked: Chat maps real
 * request phases onto them, the voice bridge maps the real `/voice/events`
 * stream, the biometrics flow drives `authenticating`, and the dashboard
 * reports backend health.
 *
 * Two states own themselves rather than being set by a caller:
 *
 * - `sleeping` — entered after {@link SLEEP_AFTER_MS} of a quiet `idle`, left
 *   on any pointer/key activity or any state change. An assistant that sits on
 *   a desktop should visibly power down, not spin at full idle forever.
 * - `listening` / `thinking` / `speaking` — driven by the real `/voice/events`
 *   stream through {@link voiceOwns}, which refuses to let audio interrupt a
 *   running tool call or a pending confirm.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

/**
 * PRD §30's eleven states, in the order the PRD lists them. This tuple is the
 * source of truth: `AIState` derives from it, so `Record<AIState, …>` tables
 * like {@link AI_STATE_LABEL} and {@link AI_STATE_TUNING} fail to compile the
 * moment a state is added without its label and tuning.
 */
export const AI_STATES = [
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
] as const

export type AIState = (typeof AI_STATES)[number]

export const AI_STATE_LABEL: Record<AIState, string> = {
  idle: 'STANDBY',
  listening: 'LISTENING',
  thinking: 'THINKING',
  processing: 'PROCESSING',
  working: 'WORKING',
  speaking: 'SPEAKING',
  success: 'SUCCESS',
  warning: 'ATTENTION',
  error: 'FAULT',
  authenticating: 'AUTHENTICATING',
  sleeping: 'SLEEPING',
}

/** Design targets used by the scene (see CoreDrive). */
export const AI_STATE_TUNING: Record<
  AIState,
  { speed: number; energy: number; ringSpeed: number }
> = {
  idle: { speed: 0.18, energy: 0.3, ringSpeed: 0.12 },
  listening: { speed: 0.3, energy: 0.5, ringSpeed: 0.3 },
  thinking: { speed: 0.55, energy: 0.62, ringSpeed: 0.55 },
  processing: { speed: 0.85, energy: 0.8, ringSpeed: 0.95 },
  working: { speed: 1.0, energy: 0.85, ringSpeed: 1.3 },
  speaking: { speed: 0.7, energy: 0.75, ringSpeed: 0.7 },
  success: { speed: 0.5, energy: 1.0, ringSpeed: 1.1 },
  warning: { speed: 0.35, energy: 0.7, ringSpeed: 0.5 },
  error: { speed: 0.4, energy: 0.95, ringSpeed: 0.7 },
  // Slow and watchful — a biometric check is deliberate, not frantic.
  authenticating: { speed: 0.26, energy: 0.55, ringSpeed: 0.22 },
  // Near-still: the core keeps breathing so it reads as asleep, not dead.
  sleeping: { speed: 0.05, energy: 0.1, ringSpeed: 0.03 },
}

/** A quiet `idle` this long powers the core down into `sleeping`. */
export const SLEEP_AFTER_MS = 180_000

/** Live work a voice frame is not allowed to interrupt. */
const VOICE_LOCKED: readonly AIState[] = ['working', 'processing', 'authenticating', 'warning']

/** The cycle voice drives unaided: quiet → listening → thinking → speaking. */
const VOICE_OWNED: readonly AIState[] = ['idle', 'sleeping', 'listening', 'thinking', 'speaking']

/**
 * Whether the `/voice/events` stream may move the core from `current` to `next`.
 *
 * Two rules, in order:
 *
 * 1. **Work wins.** `working`, `processing`, `authenticating` and `warning` (a
 *    pending confirm) are owned by Chat and the biometrics flow; voice never
 *    takes them, so the orb cannot flash LISTENING over a running tool call.
 * 2. **Voice only claims what it can own.** Returning to `idle`, or reporting
 *    its own `error` (STT/TTS failed), is allowed purely from a state voice
 *    itself put the core in — that is what stops an `idle` frame from
 *    cancelling Chat's `success`/`error` pulse mid-burst.
 *
 * Entering `listening`/`thinking`/`speaking` from a finished task is fine: the
 * user is genuinely speaking over the top of a result.
 */
export function voiceOwns(current: AIState, next: AIState): boolean {
  if (VOICE_LOCKED.includes(current)) return false
  if (next === 'idle' || next === 'error') return VOICE_OWNED.includes(current)
  return VOICE_OWNED.includes(next)
}

interface AIStateValue {
  state: AIState
  /** Current state without cancelling a pending auto-return. */
  setState: (next: AIState) => void
  /** Transient burst that falls back to `after` once `ms` elapse. */
  pulse: (kind: 'success' | 'warning' | 'error' | 'working', ms?: number, after?: AIState) => void
  /** Increments on every core click so the scene can react visually. */
  clickNonce: number
  fireClickPulse: () => void
}

const AIStateContext = createContext<AIStateValue | null>(null)

export function AIStateProvider({ children }: { children: ReactNode }) {
  const [state, setStateRaw] = useState<AIState>('idle')
  const [clickNonce, setClickNonce] = useState(0)
  const timerRef = useRef<number | undefined>(undefined)
  const sleepRef = useRef<number | undefined>(undefined)
  /** Mirrors `state` for listeners that are registered once but read it later. */
  const stateRef = useRef<AIState>('idle')

  /** Single write path, so the ref can never drift from the rendered state. */
  const commit = useCallback((next: AIState) => {
    stateRef.current = next
    setStateRaw(next)
  }, [])

  /** (Re)start the idle countdown; it only fires while the core is still quiet. */
  const armSleep = useCallback(() => {
    window.clearTimeout(sleepRef.current)
    sleepRef.current = window.setTimeout(() => {
      if (stateRef.current === 'idle') commit('sleeping')
    }, SLEEP_AFTER_MS)
  }, [commit])

  const setState = useCallback(
    (next: AIState) => {
      window.clearTimeout(timerRef.current)
      commit(next)
      armSleep()
    },
    [commit, armSleep],
  )

  const pulse = useCallback(
    (kind: 'success' | 'warning' | 'error' | 'working', ms = 1500, after: AIState = 'idle') => {
      window.clearTimeout(timerRef.current)
      commit(kind)
      timerRef.current = window.setTimeout(() => {
        commit(after)
        armSleep()
      }, ms)
    },
    [commit, armSleep],
  )

  const fireClickPulse = useCallback(() => {
    setClickNonce((value) => value + 1)
    if (stateRef.current === 'sleeping') commit('idle')
    armSleep()
  }, [commit, armSleep])

  /**
   * Start the countdown at load and keep it alive on real input: a core that
   * nobody has touched for {@link SLEEP_AFTER_MS} powers down, and the first
   * pointer or key press brings it back. `setState`/`pulse` re-arm it too, so
   * an active session never falls asleep underneath itself.
   */
  useEffect(() => {
    armSleep()
    const onActivity = () => {
      if (stateRef.current === 'sleeping') commit('idle')
      armSleep()
    }
    window.addEventListener('pointerdown', onActivity)
    window.addEventListener('keydown', onActivity)
    return () => {
      window.removeEventListener('pointerdown', onActivity)
      window.removeEventListener('keydown', onActivity)
      window.clearTimeout(sleepRef.current)
    }
  }, [armSleep, commit])

  // The pulse timeout outlives the activity listener above, so clear it too.
  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const value = useMemo(
    () => ({ state, setState, pulse, clickNonce, fireClickPulse }),
    [state, setState, pulse, clickNonce, fireClickPulse],
  )

  return <AIStateContext.Provider value={value}>{children}</AIStateContext.Provider>
}

export function useAIState(): AIStateValue {
  const value = useContext(AIStateContext)
  if (!value) throw new Error('useAIState must be used inside <AIStateProvider>')
  return value
}
