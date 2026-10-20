import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, GlobeIcon, RefreshIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  getWebConfig,
  probeWebSources,
  resetWebConfig,
  setWebConfig,
  type WebConfig,
  type WebConfigBundle,
} from '../../lib/web'

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

const SELECT_CLASS =
  'h-8 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

/** Human labels for the probe result keys the backend returns. */
const SOURCE_LABEL: Record<string, string> = {
  search: 'Search',
  weather: 'Weather',
  news: 'News',
  movies: 'Movies',
  clock: 'World clock',
}

export function WebCard() {
  const [bundle, setBundle] = useState<WebConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<WebConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [probe, setProbe] = useState<Record<string, string> | null>(null)
  const [probing, setProbing] = useState(false)

  const apply = (data: WebConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getWebConfig(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getWebConfig(controller.signal)
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
  const config: WebConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status

  const setField = <K extends keyof WebConfig>(key: K, value: WebConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof WebConfig, min: number, max: number, step: number) => (
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

  const select = (key: keyof WebConfig, options: string[]) => (
    <select
      value={String(config[key] ?? '')}
      disabled={busy !== null}
      onChange={(event) => setField(key, event.target.value as never)}
      className={SELECT_CLASS}
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  )

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      apply(await setWebConfig(draft))
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
      apply(await resetWebConfig())
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
      const result = await probeWebSources()
      setProbe(result.results)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setProbing(false)
    }
  }

  return (
    <SettingsCard
      id="web"
      title="Web intelligence"
      icon={<GlobeIcon className="size-4 text-tint" />}
      badge={
        <>
          <span
            className={`rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${
              status.enabled
                ? 'border-status-ok/40 bg-status-ok/10 text-status-ok'
                : 'border-white/15 text-muted'
            }`}
          >
            {status.enabled ? 'on' : 'off'}
          </span>
          {status.keyless ? (
            <span
              className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted"
              title="Every source is a free public endpoint — no API keys"
            >
              keyless
            </span>
          ) : null}
        </>
      }
      hint={
        <>
          Lets the model pull live information: web search, weather, news, movies, finance, an
          internet-speed test and the world clock (PRD §37). Every source is free and keyless.
          Turning this off makes all seven tools answer{' '}
          <span className="text-ink">disabled</span>. Changes apply when you press{' '}
          <span className="text-ink">Save</span>.
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
            <Row label="Enable web tools" hint="off = all seven answer 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="Web intelligence enabled"
              />
            </Row>
            <Row
              label="Allow speed test"
              hint="downloads a real payload over your link"
            >
              <Toggle
                checked={config.speed_enabled}
                disabled={busy !== null}
                onChange={(value) => setField('speed_enabled', value)}
                label="Internet speed test enabled"
              />
            </Row>
          </div>

          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Sources</p>
            <p className="font-mono text-[10px] text-muted/70">
              DuckDuckGo · Open-Meteo · RSS/HN · TVMaze · Yahoo Finance · Cloudflare
            </p>
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
              {probing ? 'Testing…' : 'Test sources'}
            </button>
            {probe ? (
              <ul className="mt-2 flex flex-col gap-1">
                {Object.entries(probe).map(([source, result]) => (
                  <li
                    key={source}
                    className="flex items-center justify-between gap-2 font-mono text-[10px]"
                  >
                    <span className="text-muted">{SOURCE_LABEL[source] ?? source}</span>
                    <span
                      className={
                        result === 'ok'
                          ? 'text-status-ok'
                          : 'max-w-[12rem] truncate text-danger'
                      }
                      title={result}
                    >
                      {result}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Retrieval</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Search results">{num('max_results', 1, 20, 1)}</Row>
            <Row label="News headlines">{num('news_items', 1, 25, 1)}</Row>
            <Row label="HTTP timeout" hint="seconds per request">
              {num('timeout_s', 1, 60, 1)}
            </Row>
            <Row label="DDG region" hint="wt-wt = worldwide">
              <input
                value={config.search_region}
                disabled={busy !== null}
                onChange={(event) => setField('search_region', event.target.value)}
                placeholder="wt-wt"
                className={`${NUM_CLASS} w-24 text-left`}
              />
            </Row>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Units &amp; speed</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Temperature">
              {select('temperature_unit', bundle.catalog.temperature_units)}
            </Row>
            <Row label="Wind speed">{select('wind_unit', bundle.catalog.wind_units)}</Row>
            <Row label="Download payload" hint="bytes for the speed test">
              {num('speed_download_bytes', 100000, 100000000, 100000)}
            </Row>
            <Row label="Upload payload" hint="0 = skip the upload leg">
              {num('speed_upload_bytes', 0, 50000000, 100000)}
            </Row>
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
            title="Drop web.json so .env / built-in defaults win again"
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
