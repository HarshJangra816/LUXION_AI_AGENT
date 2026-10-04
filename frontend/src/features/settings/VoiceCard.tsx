import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertIcon, MicIcon, MicOffIcon, RefreshIcon } from '../../components/icons'
import type { CapabilityReport } from '../../lib/capabilities'
import { useAIState } from '../../lib/aiState'
import { ApiError } from '../../lib/api'
import {
  getVoiceConfig,
  getVoiceStatus,
  recognize,
  resetVoiceConfig,
  setVoiceConfig,
  setVoiceListening,
  speak,
  STATE_LABEL,
  useVoiceEvents,
  type VoiceConfig,
  type VoiceConfigBundle,
  type VoiceEvent,
  type VoiceStatus,
} from '../../lib/voice'

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

/** A row of label + control in the same shape as the other settings cards. */
function Row({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="flex items-center justify-between gap-3 border-b border-white/8 py-2.5 last:border-b-0">
      <span className="min-w-0">
        <span className="block text-xs text-ink">{label}</span>
        {hint ? (
          <span className="block font-mono text-[10px] text-muted/70">{hint}</span>
        ) : null}
      </span>
      {children}
    </label>
  )
}

function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full border transition duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-tint/60 ${
        checked ? 'border-tint/60 bg-tint/30' : 'border-white/15 bg-white/8'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:border-tint/60'}`}
    >
      <span
        className={`absolute top-0.5 size-4 rounded-full transition duration-200 ${
          checked ? 'left-6 bg-tint' : 'left-0.5 bg-muted'
        }`}
      />
    </button>
  )
}

const NUM_CLASS =
  'h-8 w-24 shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 text-right font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

const TEXT_CLASS =
  'h-8 w-40 shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

const SELECT_CLASS =
  'h-8 w-40 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

interface VoiceCardProps {
  /** The Permissions & capabilities report — mic / speaker gates come from it. */
  caps: CapabilityReport | null
}

export function VoiceCard({ caps }: VoiceCardProps) {
  const [status, setStatus] = useState<VoiceStatus | null>(null)
  const [bundle, setBundle] = useState<VoiceConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<VoiceConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [heard, setHeard] = useState<string | null>(null)
  const [level, setLevel] = useState(0)
  const levelAtRef = useRef(0)
  const { pulse } = useAIState()

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextStatus, nextBundle] = await Promise.all([
        getVoiceStatus(signal),
        getVoiceConfig(signal),
      ])
      setStatus(nextStatus)
      setBundle(nextBundle)
      setError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setError(messageOf(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  /** Live frames: state chip + input meter (level is throttled by the server). */
  const onEvent = useCallback((event: VoiceEvent) => {
    const { type, state } = event
    if (type === 'state' && state) {
      setStatus((previous) => (previous ? { ...previous, state } : previous))
    } else if (type === 'level') {
      const now = performance.now()
      if (now - levelAtRef.current < 120) return
      levelAtRef.current = now
      setLevel(event.level)
    } else if (type === 'error') {
      setError(event.message)
    }
  }, [])

  useVoiceEvents(onEvent)

  // ---------------------------------------------------------------- derived
  const config = bundle ? { ...bundle.config, ...draft } : null
  const dirtyCount = Object.keys(draft).length
  const mic = status?.microphone
  const speaker = status?.speaker
  const micCap = caps?.capabilities.find((cap) => cap.id === 'microphone') ?? null
  const speakerCap = caps?.capabilities.find((cap) => cap.id === 'speaker') ?? null
  const live = status != null && status.listening && status.state !== 'idle'
  const micReady = status != null && status.enabled && (mic?.allowed ?? false)
  const canTestVoice = status != null && status.enabled && status.tts.enabled && (speaker?.allowed ?? false)

  const setField = <K extends keyof VoiceConfig>(key: K, value: VoiceConfig[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
  }

  const num = (key: keyof VoiceConfig, min: number, max: number, step: number) => (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={String(config?.[key] ?? '')}
      disabled={busy !== null}
      onChange={(event) => {
        const value = Number(event.target.value)
        if (Number.isFinite(value)) setField(key, value as never)
      }}
      className={NUM_CLASS}
    />
  )

  // --------------------------------------------------------------- actions
  const runLive = async () => {
    if (busy !== null || status === null) return
    setBusy('live')
    try {
      setStatus(await setVoiceListening(!live))
      setError(null)
      pulse('success', 1000)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const runPtt = async () => {
    if (busy !== null) return
    setBusy('ptt')
    setHeard(null)
    try {
      const text = (await recognize()).text.trim()
      setHeard(text || 'Nothing crossed the speech gate')
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const runSpeak = async () => {
    if (busy !== null) return
    setBusy('speak')
    try {
      await speak('Voice output is working. This is Luxion speaking.')
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    if (dirtyCount === 0 || busy !== null) return
    setBusy('save')
    try {
      setStatus(await setVoiceConfig(draft))
      setDraft({})
      setBundle(await getVoiceConfig())
      setError(null)
      pulse('success', 1200)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setBusy(null)
    }
  }

  const revert = async () => {
    if (busy !== null) return
    setBusy('revert')
    try {
      setStatus(await resetVoiceConfig())
      setDraft({})
      setBundle(await getVoiceConfig())
      setError(null)
      pulse('success', 1200)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setBusy(null)
    }
  }

  const stateChip = status ? STATE_LABEL[status.state] : '…'
  const levelWidth = `${Math.min(100, Math.round(level * 400))}%`

  return (
    <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MicIcon className="size-4 text-tint" />
          <h3 className="text-sm font-semibold text-ink">Voice</h3>
          {status ? (
            <span
              className={`rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${
                status.state === 'idle'
                  ? 'border-white/15 text-muted'
                  : status.state === 'speaking'
                    ? 'border-warning/40 bg-warning/10 text-warning'
                    : 'border-status-ok/40 bg-status-ok/10 text-status-ok'
              }`}
            >
              {stateChip}
            </span>
          ) : null}
          {live ? (
            <span className="inline-flex items-center gap-1 rounded border border-tint/40 bg-tint/10 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-tint uppercase">
              <MicIcon className="size-3" />
              wake word live
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || busy !== null}
          className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
            loading || busy !== null
              ? 'cursor-wait text-muted'
              : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
          }`}
        >
          <RefreshIcon className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <p className="mt-1.5 text-xs text-muted">
        Microphone → speech-to-text → wake word → reply → text-to-speech (PRD §26). Hardware is
        still hard-gated in{' '}
        <span className="text-ink">Permissions &amp; capabilities</span> — a denied mic or speaker
        blocks this card no matter what is set here. Changes apply when you press{' '}
        <span className="text-ink">Save</span>.
      </p>

      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
          <AlertIcon className="mt-0.5 size-4 shrink-0" />
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="cursor-pointer rounded border border-danger/40 px-2 py-0.5 text-[11px] transition duration-200 hover:bg-danger/20"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading && !config ? (
        <p className="mt-4 text-xs text-muted">Loading voice settings…</p>
      ) : null}

      {config ? (
        <>
          {/* ---------------------------------------------------- session */}
          <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                  Voice assistant
                </span>
                <Toggle
                  checked={config.master}
                  disabled={busy !== null}
                  onChange={(value) => setField('master', value)}
                  label="Voice master switch"
                />
                <span className="font-mono text-[11px] text-muted">
                  {config.master ? 'on' : 'off'}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void runLive()}
                  disabled={busy !== null || !micReady}
                  title={
                    micReady
                      ? 'Open the microphone and wait for the wake phrase'
                      : (mic?.reason ?? 'Microphone unavailable')
                  }
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                    busy !== null || !micReady
                      ? 'cursor-not-allowed border-white/10 text-muted/50'
                      : live
                        ? 'cursor-pointer border-danger/40 text-danger hover:bg-danger/10'
                        : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
                  }`}
                >
                  {live ? <MicOffIcon className="size-3.5" /> : <MicIcon className="size-3.5" />}
                  {busy === 'live'
                    ? 'Working…'
                    : live
                      ? 'Stop listening'
                      : 'Start live listening'}
                </button>
                <button
                  type="button"
                  onClick={() => void runPtt()}
                  disabled={busy !== null || !micReady || live}
                  title={
                    live
                      ? 'Turn live listening off first'
                      : (mic?.reason ?? 'Capture one utterance for the speech model')
                  }
                  className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                    busy !== null || !micReady || live
                      ? 'cursor-not-allowed border-white/10 text-muted/50'
                      : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                  }`}
                >
                  {busy === 'ptt' ? 'Listening…' : 'Test microphone'}
                </button>
                <button
                  type="button"
                  onClick={() => void runSpeak()}
                  disabled={!canTestVoice || busy !== null}
                  title={
                    canTestVoice ? 'Speak a sample sentence' : (speaker?.reason ?? 'Speaker off')
                  }
                  className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                    !canTestVoice || busy !== null
                      ? 'cursor-not-allowed border-white/10 text-muted/50'
                      : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                  }`}
                >
                  {busy === 'speak' ? 'Speaking…' : 'Test voice'}
                </button>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-panel/50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] uppercase text-muted">Microphone</span>
                  <span
                    className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                      micCap
                        ? micCap.state === 'granted'
                          ? 'border-status-ok/40 bg-status-ok/10 text-status-ok'
                          : 'border-danger/30 bg-danger/10 text-danger'
                        : 'border-white/15 text-muted'
                    }`}
                  >
                    {micCap ? micCap.state.replace('_', ' ') : (mic?.state ?? 'unknown')}
                  </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-muted/70" title={micCap?.reason}>
                  {micCap?.reason ?? mic?.reason ?? 'Windows privacy gate'}
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-tint transition-[width] duration-150"
                    style={{ width: levelWidth }}
                  />
                </div>
              </div>
              <div className="rounded-lg border border-white/10 bg-panel/50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] uppercase text-muted">Speaker</span>
                  <span
                    className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                      speakerCap
                        ? speakerCap.state === 'granted'
                          ? 'border-status-ok/40 bg-status-ok/10 text-status-ok'
                          : 'border-danger/30 bg-danger/10 text-danger'
                        : 'border-white/15 text-muted'
                    }`}
                  >
                    {speakerCap ? speakerCap.state.replace('_', ' ') : (speaker?.state ?? 'unknown')}
                  </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-muted/70" title={speakerCap?.reason}>
                  {speakerCap?.reason ?? speaker?.reason ?? 'In-app consent (default on)'}
                </p>
                <p className="mt-2 font-mono text-[10px] text-muted/60">
                  {status
                    ? `${status.tts.provider} · ${status.tts.rate >= 0 ? '+' : ''}${status.tts.rate} rate · ${status.tts.volume}%`
                    : '—'}
                </p>
              </div>
            </div>

            {heard ? (
              <p className="mt-3 rounded-lg border border-tint/30 bg-tint/8 px-3 py-2 text-xs text-tint">
                Heard: “{heard}”
              </p>
            ) : null}

            <p className="mt-3 font-mono text-[10px] text-muted/60">
              {status
                ? `model ${status.stt.model}${status.stt.loaded ? ' · loaded' : ' · warms up on first use'} · mic “${status.capture.device}” · armed ${status.wake.armed_for_s}s`
                : '—'}
            </p>
          </div>

          {/* -------------------------------------------------- microphone */}
          <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Microphone
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Input device" hint="name survives index shifts; blank = system default">
                  <select
                    value={config.mic_device}
                    disabled={busy !== null}
                    onChange={(event) => setField('mic_device', event.target.value)}
                    className={`${SELECT_CLASS} max-w-[16rem]`}
                  >
                    <option value="">System default</option>
                    {(status?.devices ?? []).map((device) => (
                      <option key={device.index} value={device.name}>
                        {device.name}
                        {device.is_default ? ' (default)' : ''}
                      </option>
                    ))}
                    {config.mic_device &&
                    !(status?.devices ?? []).some((device) => device.name === config.mic_device) ? (
                      <option value={config.mic_device}>{config.mic_device}</option>
                    ) : null}
                  </select>
                </Row>
                <Row label="Speech gate" hint="RMS threshold before a block counts as speech">
                  {num('vad_threshold', 0.001, 0.5, 0.001)}
                </Row>
                <Row label="Minimum speech" hint="seconds above the gate to open an utterance">
                  {num('min_speech_s', 0, 2, 0.1)}
                </Row>
                <Row label="Trailing silence" hint="seconds of quiet that closes an utterance">
                  {num('silence_s', 0.2, 5, 0.1)}
                </Row>
                <Row label="Max utterance" hint="hard cap per command, seconds">
                  {num('max_utterance_s', 3, 240, 1)}
                </Row>
                <Row label="Push-to-talk budget" hint="capture window for the composer mic">
                  {num('ptt_timeout_s', 3, 120, 1)}
                </Row>
              </div>
            </div>

            {/* ------------------------------------------------------ wake */}
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Wake word
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Wake word" hint="what arms a command in live listening">
                  <input
                    value={config.wake_phrase}
                    disabled={busy !== null}
                    onChange={(event) => setField('wake_phrase', event.target.value)}
                    className={TEXT_CLASS}
                  />
                </Row>
                <Row label="Enabled" hint="off = every utterance is treated as a command">
                  <Toggle
                    checked={config.wake_enabled}
                    disabled={busy !== null}
                    onChange={(value) => setField('wake_enabled', value)}
                    label="Wake word enabled"
                  />
                </Row>
                <Row label="Armed for" hint="seconds a bare wake phrase waits for the command">
                  {num('wake_arm_s', 1, 120, 1)}
                </Row>
                <Row label="Barge-in" hint="talking over a reply cuts it off (PRD §26)">
                  <Toggle
                    checked={config.barge_in}
                    disabled={busy !== null}
                    onChange={(value) => setField('barge_in', value)}
                    label="Barge in on speech"
                  />
                </Row>
              </div>
            </div>
          </div>

          {/* ------------------------------------------------------- STT/TTS */}
          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Speech to text
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Provider" hint="PRD §5.5 — cloud providers plug in later">
                  <input value={config.stt_provider} readOnly className={`${TEXT_CLASS} opacity-60`} />
                </Row>
                <Row label="Model" hint="faster-whisper id, e.g. base.en / small.en">
                  <input
                    value={config.stt_model}
                    disabled={busy !== null}
                    onChange={(event) => setField('stt_model', event.target.value)}
                    className={TEXT_CLASS}
                  />
                </Row>
                <Row label="Device" hint="auto = CPU int8">
                  <select
                    value={config.stt_device}
                    disabled={busy !== null}
                    onChange={(event) => setField('stt_device', event.target.value)}
                    className={SELECT_CLASS}
                  >
                    <option value="auto">auto</option>
                    <option value="cpu">cpu</option>
                    <option value="cuda">cuda</option>
                  </select>
                </Row>
                <Row label="Compute type">
                  <select
                    value={config.stt_compute_type}
                    disabled={busy !== null}
                    onChange={(event) => setField('stt_compute_type', event.target.value)}
                    className={SELECT_CLASS}
                  >
                    <option value="int8">int8</option>
                    <option value="float16">float16</option>
                    <option value="float32">float32</option>
                  </select>
                </Row>
                <Row label="Language" hint="blank = auto-detect (.en models stay English)">
                  <input
                    value={config.stt_language}
                    disabled={busy !== null}
                    placeholder="auto"
                    onChange={(event) => setField('stt_language', event.target.value)}
                    className={TEXT_CLASS}
                  />
                </Row>
              </div>
            </div>

            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Text to speech
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Provider" hint="windows = SAPI5 · omnivoice = local neural voice">
                  <select
                    value={config.tts_provider}
                    disabled={busy !== null}
                    onChange={(event) => setField('tts_provider', event.target.value)}
                    className={SELECT_CLASS}
                  >
                    <option value="windows">windows</option>
                    <option value="omnivoice">omnivoice</option>
                  </select>
                </Row>
                <Row label="Speak replies" hint="off = voice replies stay text-only">
                  <Toggle
                    checked={config.tts_enabled}
                    disabled={busy !== null}
                    onChange={(value) => setField('tts_enabled', value)}
                    label="Text to speech enabled"
                  />
                </Row>
                <Row label="Rate" hint="-50 … +100 around the voice's natural pace">
                  {num('tts_rate', -50, 100, 5)}
                </Row>
                <Row label="Volume" hint="0–100 %">
                  {num('tts_volume', 0, 100, 5)}
                </Row>
                {config.tts_provider === 'omnivoice' ? (
                  <>
                    <Row label="Model" hint="Hugging Face id or a local model directory">
                      <input
                        value={config.tts_model}
                        disabled={busy !== null}
                        placeholder="k2-fsa/OmniVoice"
                        onChange={(event) => setField('tts_model', event.target.value)}
                        className={TEXT_CLASS}
                      />
                    </Row>
                    <Row
                      label="Voice design"
                      hint="comma separated: gender, age, pitch, style, accent — blank = random voice"
                    >
                      <input
                        value={config.tts_instruct}
                        disabled={busy !== null}
                        placeholder="female, young adult, moderate pitch"
                        onChange={(event) => setField('tts_instruct', event.target.value)}
                        className={TEXT_CLASS}
                      />
                    </Row>
                    <Row label="Steps" hint="diffusion steps — lower is faster on the CPU">
                      {num('tts_steps', 4, 64, 1)}
                    </Row>
                    <Row label="Language" hint="blank = let the model decide (English, en, …)">
                      <input
                        value={config.tts_language}
                        disabled={busy !== null}
                        placeholder="auto"
                        onChange={(event) => setField('tts_language', event.target.value)}
                        className={TEXT_CLASS}
                      />
                    </Row>
                  </>
                ) : null}
              </div>
            </div>
          </div>

          <p className="mt-4 text-[11px] text-muted/70">
            Voice profiles and speaker verification arrive with Phase 27 (voice authentication) —
            recognition answers <span className="text-ink">what</span> was said, verification answers{' '}
            <span className="text-ink">who</span> said it.
          </p>

          {/* ------------------------------------------------------- actions */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
            <span className="font-mono text-[10px] text-muted/70">
              {dirtyCount === 0
                ? 'no pending changes'
                : `${dirtyCount} unsaved change${dirtyCount === 1 ? '' : 's'} → stored in voice.json`}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDraft({})}
                disabled={dirtyCount === 0 || busy !== null}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  dirtyCount === 0 || busy !== null
                    ? 'cursor-default border-white/10 text-muted/40'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                }`}
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => void revert()}
                disabled={busy !== null}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null
                    ? 'cursor-wait border-white/10 text-muted/50'
                    : 'cursor-pointer border-white/15 text-muted hover:border-danger/50 hover:text-danger'
                }`}
              >
                {busy === 'revert' ? 'Resetting…' : 'Reset to .env'}
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={dirtyCount === 0 || busy !== null}
                className={`rounded-lg px-4 py-1.5 text-xs transition duration-200 ${
                  dirtyCount === 0 || busy !== null
                    ? 'cursor-default bg-panel-2 text-muted/50'
                    : 'cursor-pointer bg-accent text-on-accent hover:brightness-110'
                }`}
              >
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </>
      ) : null}
    </section>
  )
}
