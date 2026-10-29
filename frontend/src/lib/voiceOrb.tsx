/**
 * Global voice → core bridge (PRD §29 "voice activation").
 *
 * Mounted once in `main.tsx`, above the router, so the orb reacts to the real
 * `/voice/events` stream on **every** page. ChatPage keeps its own
 * subscription for the composer hints and for running commands spoken on the
 * Chat page; the backend fans each frame out to every subscriber, so the two
 * coexist instead of duplicating the work.
 *
 * Two jobs:
 *
 * 1. Translate `state` frames into the PRD §30 core states, guarded by
 *    `voiceOwns` so audio can never interrupt a running tool call or a
 *    pending confirm.
 * 2. Own the core's click-to-listen affordance — `toggleListening` opens or
 *    closes the continuous wake-word session, and a refusal (voice switched
 *    off, microphone capability denied) is reported rather than swallowed.
 *
 * `command` frames go to the fallback App registers while Chat is not the
 * active page, so a wake-word command spoken on the dashboard reaches the
 * composer instead of vanishing.
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

import { useAIState, voiceOwns, type AIState } from './aiState'
import {
  flipVoiceListening,
  getVoiceStatus,
  useVoiceEvents,
  type VoiceEvent,
  type VoiceState,
} from './voice'

/** `/voice/events` `state` frames → the PRD §30 core state they mean. */
const VOICE_STATE_TO_AI: Record<VoiceState, AIState> = {
  idle: 'idle',
  listening: 'listening',
  transcribing: 'thinking',
  speaking: 'speaking',
}

type VoiceCommandFallback = (text: string) => void

/**
 * Receives every `command` frame. App registers a handler that acts only while
 * Chat is *not* the active page (on Chat, ChatPage owns its own frames), which
 * is what keeps a spoken command from being handled twice or not at all.
 */
let commandFallback: VoiceCommandFallback | null = null

/** Register (or clear) the handler for voice commands spoken off the Chat page. */
export function setVoiceCommandFallback(handler: VoiceCommandFallback | null): void {
  commandFallback = handler
}

interface VoiceOrbValue {
  /** The continuous wake-word session is open. */
  listening: boolean
  /** A toggle request is in flight — clicks are ignored meanwhile. */
  busy: boolean
  /** Last refusal from the backend (voice off, mic denied); `null` = none. */
  notice: string | null
  /** Open the wake-word session if it is closed, close it if it is open. */
  toggleListening: () => Promise<void>
}

const VoiceOrbContext = createContext<VoiceOrbValue | null>(null)

export function VoiceOrbProvider({ children }: { children: ReactNode }) {
  const { state, setState, pulse } = useAIState()
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  /**
   * Latest backend voice state without a re-render. Read when composing an
   * error pulse: a failed transcription must return the core to LISTENING if
   * the microphone is still open, not to STANDBY.
   */
  const voiceStateRef = useRef<VoiceState | null>(null)

  const handleEvent = useCallback(
    (event: VoiceEvent) => {
      switch (event.type) {
        case 'state': {
          if (!event.state) return
          voiceStateRef.current = event.state
          const next = VOICE_STATE_TO_AI[event.state]
          if (voiceOwns(state, next)) setState(next)
          return
        }
        case 'command': {
          const text = event.text.trim()
          if (text) commandFallback?.(text)
          return
        }
        case 'error': {
          if (!event.message) return
          // Real STT/TTS failure — but only from a state voice may claim, so a
          // fault in speech never overwrites a running tool call.
          if (voiceOwns(state, 'error')) {
            pulse('error', 1600, voiceStateRef.current === 'listening' ? 'listening' : 'idle')
          }
          return
        }
        default:
          return
      }
    },
    [state, setState, pulse],
  )

  useVoiceEvents(handleEvent)

  // Seed the click affordance from the backend — the session may already have
  // been opened from Settings → Voice, and the button must not lie about it.
  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    getVoiceStatus(controller.signal)
      .then((status) => setListening(status.listening))
      .catch(() => undefined) // voice optional: the click reports its own error
    return () => controller.abort()
  }, [])

  const toggleListening = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      // Read first, then flip — see `flipVoiceListening`. Settings → Voice and
      // the composer's toggle can both change the session behind our back, and
      // a stale guess would press the wrong button.
      const status = await flipVoiceListening()
      setListening(status.listening)
      setNotice(null)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught)
      setNotice(message)
      pulse('error', 1800)
    } finally {
      setBusy(false)
    }
  }, [busy, pulse])

  const value = useMemo<VoiceOrbValue>(
    () => ({ listening, busy, notice, toggleListening }),
    [listening, busy, notice, toggleListening],
  )

  return <VoiceOrbContext.Provider value={value}>{children}</VoiceOrbContext.Provider>
}

export function useVoiceOrb(): VoiceOrbValue {
  const value = useContext(VoiceOrbContext)
  if (!value) throw new Error('useVoiceOrb must be used inside <VoiceOrbProvider>')
  return value
}
