import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, PhoneIcon, RefreshIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  closeWhatsAppSession,
  getWhatsAppConfig,
  getWhatsAppSession,
  openWhatsAppSession,
  resetWhatsAppConfig,
  setWhatsAppConfig,
  type WhatsAppConfig,
  type WhatsAppConfigBundle,
  type WhatsAppSession,
} from '../../lib/whatsapp'

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

const ACTION_CLASS =
  'rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200'

export function WhatsAppCard() {
  const [bundle, setBundle] = useState<WhatsAppConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<WhatsAppConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [session, setSession] = useState<WhatsAppSession | null>(null)
  const [waiting, setWaiting] = useState(false)

  const apply = (data: WhatsAppConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getWhatsAppConfig(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getWhatsAppConfig(controller.signal)
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

  // While a QR is on screen, poll for the scan completing (the status leg
  // never returns a QR — keep showing the one the session leg produced).
  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => {
      getWhatsAppSession()
        .then((result) => {
          if (result.logged_in) setWaiting(false)
          setSession((prev) => (result.qr === null && prev ? { ...result, qr: prev.qr } : result))
        })
        .catch(() => {
          // Transient polling failure — the next tick retries.
        })
    }, 3000)
    return () => window.clearInterval(timer)
  }, [waiting])

  if (!bundle) return null
  const config: WhatsAppConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status
  const linked = session?.logged_in === true || status.logged_in === true

  const setField = <K extends keyof WhatsAppConfig>(key: K, value: WhatsAppConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof WhatsAppConfig, min: number, max: number, step: number) => (
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

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      apply(await setWhatsAppConfig(draft))
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
      apply(await resetWhatsAppConfig())
      setSaved(false)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const connect = async () => {
    setBusy('session')
    setError(null)
    try {
      const result = await openWhatsAppSession()
      setSession(result)
      setWaiting(result.running && result.logged_in === false)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const close = async () => {
    setBusy('close')
    setError(null)
    try {
      await closeWhatsAppSession()
      setSession(null)
      setWaiting(false)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SettingsCard
      id="whatsapp"
      title="WhatsApp"
      icon={<PhoneIcon className="size-4 text-tint" />}
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
          {linked ? (
            <span
              className="rounded border border-status-ok/40 bg-status-ok/10 px-1.5 py-0.5 font-mono text-[10px] text-status-ok"
              title="A WhatsApp Web session is logged in"
            >
              linked
            </span>
          ) : null}
          {waiting ? (
            <span
              className="rounded border border-tint/40 px-1.5 py-0.5 font-mono text-[10px] text-tint"
              title="Waiting for the QR to be scanned"
            >
              scan qr
            </span>
          ) : null}
        </>
      }
      hint={
        <>
          Lets the model message your contacts: a Playwright session on web.whatsapp.com with a
          persistent profile (the login survives restarts), plus the{' '}
          <span className="text-ink">whatsapp://</span> protocol hand-off to the desktop app (PRD
          §33.3). No Meta business account or cloud API is involved — sending is browser
          automation, so WhatsApp Web redesigns can break it. Off makes every whatsapp tool answer{' '}
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
        <div className="lg:col-span-2">
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Session</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-ink">
                {linked
                  ? 'Linked — the session stays logged in across restarts.'
                  : waiting
                    ? 'Scan the QR with your phone to link this session.'
                    : session?.running
                      ? 'Session running, not logged in yet.'
                      : 'No session running — connect to launch one.'}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void connect()}
                  disabled={busy !== null || !status.enabled || waiting}
                  className={`${ACTION_CLASS} ${
                    busy !== null || !status.enabled || waiting
                      ? 'cursor-not-allowed border-white/10 text-muted/50'
                      : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
                  }`}
                >
                  {busy === 'session' ? 'Launching…' : linked ? 'Reconnect' : 'Connect'}
                </button>
                {session?.running ? (
                  <button
                    type="button"
                    onClick={() => void close()}
                    disabled={busy !== null}
                    className={`${ACTION_CLASS} ${
                      busy !== null
                        ? 'cursor-not-allowed border-white/10 text-muted/50'
                        : 'cursor-pointer border-white/15 text-muted hover:border-danger/50 hover:text-danger'
                    }`}
                  >
                    {busy === 'close' ? 'Closing…' : 'Close'}
                  </button>
                ) : null}
              </div>
            </div>

            {waiting && session?.qr ? (
              <div className="mt-3 flex flex-wrap items-center gap-4">
                <img
                  src={session.qr}
                  alt="WhatsApp login QR code"
                  className="size-52 rounded-lg border border-white/15 bg-white p-2"
                />
                <div className="min-w-40 flex-1">
                  <p className="text-xs text-ink">How to scan</p>
                  <ol className="mt-1 list-inside list-decimal font-mono text-[10px] text-muted/80">
                    <li>Open WhatsApp on your phone</li>
                    <li>Settings → Linked devices</li>
                    <li>Link a device → point the camera here</li>
                  </ol>
                  <p className="mt-2 font-mono text-[10px] text-tint">
                    waiting for the scan — checking every 3s…
                  </p>
                </div>
              </div>
            ) : null}

            <p className="mt-3 font-mono text-[10px] text-muted/70">
              profile: {status.profile_dir || 'whatsapp_profile (in the data dir)'}
              {session?.url ? ` · ${session.url}` : ''}
            </p>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            Automation
          </h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Enable whatsapp tools" hint="off = every tool answers 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="WhatsApp enabled"
              />
            </Row>
            <Row label="Headless" hint="no visible window while automating">
              <Toggle
                checked={config.headless}
                disabled={busy !== null}
                onChange={(value) => setField('headless', value)}
                label="Headless session"
              />
            </Row>
            <Row label="Action timeout" hint="seconds per search/type/read">
              {num('timeout_s', 5, 120, 1)}
            </Row>
            <Row label="Login timeout" hint="seconds to wait for a scan">
              {num('login_timeout_s', 5, 300, 5)}
            </Row>
          </div>
          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Profile directory</p>
            <input
              value={config.profile_dir}
              disabled={busy !== null}
              placeholder="empty = whatsapp_profile in the data dir"
              onChange={(event) => setField('profile_dir', event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/15 bg-surface/70 px-2 py-1.5 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
            />
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
            title="Drop whatsapp.json so .env / built-in defaults win again"
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
