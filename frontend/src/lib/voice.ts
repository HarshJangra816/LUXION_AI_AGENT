/**
 * Voice pipeline (`/api/voice`) — Phase 4 (PRD §26, §5.5, §5.6, §32).
 *
 * Mirrors `backend/luxion/api/routes/voice.py` and the frames emitted by
 * `backend/luxion/voice/manager.py`:
 *
 *   GET    /voice             status (state, devices, gates, effective config)
 *   POST   /voice/listen      {on}      wake-word session on/off
 *   POST   /voice/recognize   one utterance → its transcript (push-to-talk)
 *   POST   /voice/speak       {text}    synthesize + play a reply
 *   POST   /voice/stop        interrupt playback
 *   GET    /voice/events      SSE: state | level | transcript | wake | command
 *                             | spoken | error | ping
 *   GET    /voice/config      effective settings + built-in defaults
 *   PUT    /voice/config      partial patch, persisted to `voice.json`
 *   DELETE /voice/config      back to `.env` defaults
 *
 * The microphone and the speaker are still hard-gated by the Phase 3.5
 * capability check on the server: every refusal arrives here as an `ApiError`
 * with the OS/consent reason as its message.
 */

import { useEffect, useRef } from 'react'
import { API_BASE, request } from './api'
import { readSse } from './sse'

export type VoiceState = 'idle' | 'listening' | 'transcribing' | 'speaking'

export type VoiceEventType =
  | 'state'
  | 'level'
  | 'transcript'
  | 'wake'
  | 'command'
  | 'spoken'
  | 'error'
  | 'ping'

/** One frame on `GET /voice/events` (`type` doubles as the SSE event name). */
export interface VoiceEvent {
  type: VoiceEventType
  /** Latest state; only set on `state` frames. */
  state: VoiceState | null
  /** Transcript text, or the wake-stripped command on `command` frames. */
  text: string
  /** Input level 0..1 on `level` frames. */
  level: number
  wake: boolean
  interrupted: boolean
  message: string
  at: number
}

export interface VoiceDeviceInfo {
  index: number
  name: string
  channels: number
  rate: number
  is_default: boolean
}

export interface CapabilityView {
  allowed: boolean
  state: string
  reason: string
}

export interface VoiceStatus {
  enabled: boolean
  state: VoiceState
  listening: boolean
  armed: boolean
  speaking: boolean
  stt: {
    provider: string
    model: string
    device: string
    compute_type: string
    language: string
    loaded: boolean
  }
  tts: { provider: string; enabled: boolean; rate: number; volume: number }
  wake: { enabled: boolean; phrase: string; armed_for_s: number }
  capture: {
    device: string
    vad_threshold: number
    min_speech_s: number
    silence_s: number
    max_utterance_s: number
    barge_in: boolean
    ptt_timeout_s: number
    level: number
    gate: number
  }
  device: { index: number | null; name: string } | null
  devices: VoiceDeviceInfo[]
  microphone: CapabilityView
  speaker: CapabilityView
  last_error: string | null
}

/** Every knob `PUT /voice/config` accepts (PRD §32 Settings → Voice). */
export interface VoiceConfig {
  master: boolean
  stt_provider: string
  stt_model: string
  stt_device: string
  stt_compute_type: string
  stt_language: string
  tts_provider: string
  tts_enabled: boolean
  tts_rate: number
  tts_volume: number
  tts_model: string
  tts_instruct: string
  tts_steps: number
  tts_language: string
  wake_enabled: boolean
  wake_phrase: string
  wake_arm_s: number
  mic_device: string
  vad_threshold: number
  min_speech_s: number
  silence_s: number
  max_utterance_s: number
  barge_in: boolean
  ptt_timeout_s: number
}

export interface VoiceConfigBundle {
  config: VoiceConfig
  defaults: VoiceConfig
}

export interface SpeakResult {
  started: boolean
  interrupted: boolean
  reason?: string
}

const jsonBody = (payload: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export function getVoiceStatus(signal?: AbortSignal): Promise<VoiceStatus> {
  return request<VoiceStatus>('/voice', { signal })
}

/** Open (`true`) or close (`false`) the continuous wake-word session. */
export function setVoiceListening(on: boolean): Promise<VoiceStatus> {
  return request<VoiceStatus>('/voice/listen', jsonBody({ on }))
}

/** Push-to-talk: one utterance → its transcript (`""` when nothing was said). */
export function recognize(timeoutS?: number): Promise<{ text: string }> {
  const payload = timeoutS === undefined ? {} : { timeout_s: timeoutS }
  return request<{ text: string }>('/voice/recognize', jsonBody(payload))
}

/** Speak a reply. `block=false` reports completion on the event stream. */
export function speak(text: string, block = false): Promise<SpeakResult> {
  return request<SpeakResult>('/voice/speak', jsonBody({ text, block }))
}

/** Interrupt whatever is playing (the composer's Stop button). */
export function stopSpeaking(): Promise<{ stopped: boolean }> {
  return request<{ stopped: boolean }>('/voice/stop', jsonBody({}))
}

export function getVoiceConfig(signal?: AbortSignal): Promise<VoiceConfigBundle> {
  return request<VoiceConfigBundle>('/voice/config', { signal })
}

/** Persist the Settings → Voice edits; the reply is the rebuilt status. */
export function setVoiceConfig(patch: Partial<VoiceConfig>): Promise<VoiceStatus> {
  return request<VoiceStatus>('/voice/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `voice.json` so `.env` / built-in defaults win again. */
export function resetVoiceConfig(): Promise<VoiceStatus> {
  return request<VoiceStatus>('/voice/config', { method: 'DELETE' })
}

/** Human label for the composer / Settings state chip. */
export const STATE_LABEL: Record<VoiceState, string> = {
  idle: 'voice idle',
  listening: 'listening',
  transcribing: 'transcribing',
  speaking: 'speaking',
}

/**
 * Subscribe to `GET /voice/events` while `enabled`.
 *
 * The stream is read with the shared fetch-based SSE reader (EventSource
 * cannot be configured for the Tauri origin) and reconnects with a capped
 * backoff; the handler is kept in a ref so a changing callback never tears
 * the connection down.
 */
export function useVoiceEvents(
  onEvent: (event: VoiceEvent) => void,
  enabled = true,
): void {
  const handlerRef = useRef(onEvent)

  useEffect(() => {
    handlerRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let attempt = 0
    const controller = new AbortController()

    const emit = (frame: { data: string }) => {
      try {
        const payload = JSON.parse(frame.data) as VoiceEvent
        if (payload && typeof payload.type === 'string') handlerRef.current(payload)
      } catch {
        // a malformed frame must not kill the stream
      }
    }

    const run = async () => {
      while (!stopped) {
        try {
          const response = await fetch(`${API_BASE}/voice/events`, {
            signal: controller.signal,
            headers: { Accept: 'text/event-stream' },
          })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          attempt = 0
          for await (const frame of readSse(response)) emit(frame)
        } catch {
          if (stopped || controller.signal.aborted) return
        }
        attempt += 1
        const delay = Math.min(15_000, 750 * 2 ** Math.min(attempt, 5))
        await new Promise((resolve) => {
          setTimeout(resolve, delay)
        })
      }
    }

    void run()
    return () => {
      stopped = true
      controller.abort()
    }
  }, [enabled])
}
