import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, EyeIcon, RefreshIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  analyzeImage,
  getVisionConfig,
  probeVision,
  resetVisionConfig,
  setVisionConfig,
  type VisionConfig,
  type VisionConfigBundle,
  type VisionProbe,
} from '../../lib/vision'

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
  'h-8 w-full shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

export function VisionCard() {
  const [bundle, setBundle] = useState<VisionConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<VisionConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [probe, setProbe] = useState<VisionProbe | null>(null)
  const [probing, setProbing] = useState(false)
  const [answer, setAnswer] = useState<string | null>(null)
  const [question, setQuestion] = useState('What is on this screen?')

  const apply = (data: VisionConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getVisionConfig(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getVisionConfig(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        apply(data)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(messageOf(err))
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  if (!bundle) return null
  const config: VisionConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status

  const setField = <K extends keyof VisionConfig>(key: K, value: VisionConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof VisionConfig, min: number, max: number, step: number) => (
    <input
      type="number"
      value={String(config[key] ?? '')}
      min={min}
      max={max}
      step={step}
      disabled={busy !== null}
      onChange={(event) => setField(key, Number(event.target.value) as never)}
      className={NUM_CLASS}
    />
  )

  const text = (
    key: 'model' | 'provider' | 'base_url' | 'api_key_env' | 'prompt',
    placeholder: string,
  ) => (
    <input
      value={config[key]}
      placeholder={placeholder}
      disabled={busy !== null}
      onChange={(event) => setField(key, event.target.value as never)}
      className={TEXT_CLASS}
    />
  )

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      apply(await setVisionConfig(draft))
      setSaved(true)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const discard = () => {
    setDraft({})
    setSaved(false)
  }

  const resetAll = async () => {
    setBusy('reset')
    setError(null)
    try {
      apply(await resetVisionConfig())
      setSaved(false)
      setProbe(null)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const runProbe = async () => {
    setProbing(true)
    setError(null)
    try {
      setProbe(await probeVision())
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setProbing(false)
    }
  }

  const runAnalyze = async () => {
    setBusy('analyze')
    setError(null)
    setAnswer(null)
    try {
      const result = await analyzeImage({ screenshot: true, question })
      setAnswer(result.answer)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SettingsCard
      id="vision"
      title="Vision"
      icon={<EyeIcon className="size-4 text-tint" />}
      badge={
        <span
          className={`rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${
            status.enabled
              ? 'border-status-ok/40 bg-status-ok/10 text-status-ok'
              : 'border-white/15 text-muted'
          }`}
        >
          {status.enabled ? 'on' : 'off'}
        </span>
      }
      hint={
        <>
          Lets Luxion look at pictures: the <span className="text-ink">analyze_image</span> and{' '}
          <span className="text-ink">analyze_screenshot</span> tools hand a picture to a vision
          model (PRD §5.9, §33.15). The model call reuses your existing chat provider, so no new
          API key and no new dependency. Turning this off makes both tools answer{' '}
          <span className="text-ink">disabled</span>.
        </>
      }
      actions={
        <button
          type="button"
          onClick={() => {
            setLoading(true)
            void load()
          }}
          disabled={loading || busy !== null || probing}
          className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
            loading || busy !== null || probing
              ? 'cursor-wait text-muted'
              : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
          }`}
        >
          <RefreshIcon className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      }
    >
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

      <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Access</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Enable vision tools" hint="off = both tools answer 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="Vision enabled"
              />
            </Row>
            <Row label="Vision model" hint="empty = reuse the chat model">
              {text('model', 'qwen2.5vl:3b')}
            </Row>
            <Row label="Provider" hint="empty = the chat adapter">
              {text('provider', 'ollama')}
            </Row>
          </div>

          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Endpoint</p>
            <p className="font-mono text-[10px] text-muted/70">
              Leave empty to use the chat provider's URL and key.
            </p>
            <div className="mt-2 space-y-2">
              <input
                value={config.base_url}
                placeholder="http://127.0.0.1:11434"
                disabled={busy !== null}
                onChange={(event) => setField('base_url', event.target.value)}
                className={TEXT_CLASS}
              />
              <input
                value={config.api_key_env}
                placeholder="VISION_API_KEY"
                disabled={busy !== null}
                onChange={(event) => setField('api_key_env', event.target.value)}
                className={TEXT_CLASS}
              />
            </div>
            <button
              type="button"
              onClick={() => void runProbe()}
              disabled={probing}
              className={`mt-2 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
                probing
                  ? 'cursor-wait text-muted'
                  : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
              }`}
            >
              {probing ? 'Testing…' : 'Test endpoint'}
            </button>
            {probe ? (
              <p
                className={`mt-2 font-mono text-[10px] ${
                  probe.ok && probe.found ? 'text-status-ok' : 'text-danger'
                }`}
              >
                {probe.ok
                  ? probe.found
                    ? `${probe.provider} · ${probe.model} · ${probe.models.length} models`
                    : `${probe.provider} reachable, but '${probe.model}' is not listed`
                  : (probe.error ?? 'unreachable')}
              </p>
            ) : null}
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Limits</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Images per request">{num('max_images', 1, 8, 1)}</Row>
            <Row label="Longest edge" hint="pixels before downscaling">
              {num('max_dimension', 256, 4096, 64)}
            </Row>
            <Row label="Max payload" hint="bytes">
              {num('max_bytes', 100000, 50000000, 100000)}
            </Row>
            <Row label="Timeout" hint="seconds per call">
              {num('timeout_s', 1, 600, 10)}
            </Row>
          </div>

          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Default prompt</p>
            <p className="font-mono text-[10px] text-muted/70">
              Used when the model does not ask a specific question.
            </p>
            <textarea
              value={config.prompt}
              rows={3}
              disabled={busy !== null}
              onChange={(event) => setField('prompt', event.target.value)}
              className="mt-2 w-full resize-y rounded-lg border border-white/15 bg-surface/70 px-2 py-1.5 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
            />
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Try it</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Look at the screen</p>
            <p className="font-mono text-[10px] text-muted/70">
              Captures the display and asks the vision model. Needs the screen-capture consent.
            </p>
            <input
              value={question}
              placeholder="What is on this screen?"
              disabled={busy !== null}
              onChange={(event) => setQuestion(event.target.value)}
              className={`${TEXT_CLASS} mt-2`}
            />
            <button
              type="button"
              onClick={() => void runAnalyze()}
              disabled={busy !== null || !config.enabled}
              className={`mt-2 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
                busy !== null || !config.enabled
                  ? 'cursor-not-allowed border-white/10 text-muted/50'
                  : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
              }`}
            >
              {busy === 'analyze' ? 'Looking…' : 'Analyze screen'}
            </button>
            {answer ? (
              <p className="mt-2 rounded-lg border border-white/10 bg-surface/70 px-2 py-1.5 text-[11px] whitespace-pre-wrap text-ink">
                {answer}
              </p>
            ) : null}
          </div>

          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Models that work</p>
            <p className="font-mono text-[10px] text-muted/70">
              {bundle.catalog.suggested_models.join(' · ')}
            </p>
            <p className="mt-1 font-mono text-[10px] text-muted/70">
              reads {bundle.catalog.supported_types.join(' ')}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-[10px] text-muted/70">
          {dirty
            ? 'unsaved changes'
            : saved
              ? 'saved — the next tool call uses the new settings'
              : 'settings match the saved state'}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={resetAll}
            disabled={busy !== null}
            title="Drop vision.json so .env / built-in defaults win again"
            className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
              busy !== null
                ? 'cursor-not-allowed border-white/10 text-muted/50'
                : 'cursor-pointer border-white/15 text-muted hover:border-danger/50 hover:text-danger'
            }`}
          >
            {busy === 'reset' ? 'Resetting…' : 'Reset to .env'}
          </button>
          <button
            type="button"
            onClick={discard}
            disabled={busy !== null || !dirty}
            className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
              busy !== null || !dirty
                ? 'cursor-not-allowed border-white/10 text-muted/50'
                : 'cursor-pointer border-white/15 text-muted hover:border-white/30 hover:text-ink'
            }`}
          >
            Discard
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy !== null || !dirty}
            className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
              busy !== null || !dirty
                ? 'cursor-not-allowed border-white/10 text-muted/50'
                : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
            }`}
          >
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </SettingsCard>
  )
}
