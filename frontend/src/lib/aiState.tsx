/**
 * AI core state — drives the 3D scene's reactivity and the status HUD.
 *
 * States are never faked: Chat maps real request phases onto them, and the
 * dashboard reports backend health. Clicking the core only fires a visual
 * pulse (there is no voice backend yet, so it must not pretend to listen).
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

export type AIState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'processing'
  | 'working'
  | 'speaking'
  | 'success'
  | 'warning'
  | 'error'

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

  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const setState = useCallback((next: AIState) => {
    window.clearTimeout(timerRef.current)
    setStateRaw(next)
  }, [])

  const pulse = useCallback(
    (kind: 'success' | 'warning' | 'error' | 'working', ms = 1500, after: AIState = 'idle') => {
      window.clearTimeout(timerRef.current)
      setStateRaw(kind)
      timerRef.current = window.setTimeout(() => setStateRaw(after), ms)
    },
    [],
  )

  const fireClickPulse = useCallback(() => setClickNonce((value) => value + 1), [])

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
