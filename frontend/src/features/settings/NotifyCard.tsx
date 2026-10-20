import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, BellIcon, RefreshIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  getNotifyConfig,
  resetNotifyConfig,
  setNotifyConfig,
  testNotify,
  type NotificationConfig,
  type NotifyConfigBundle,
} from '../../lib/notify'

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

export function NotifyCard() {
  const [bundle, setBundle] = useState<NotifyConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<NotificationConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)

  const apply = (data: NotifyConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getNotifyConfig(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getNotifyConfig(controller.signal)
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
  const config: NotificationConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status

  const setField = <K extends keyof NotificationConfig>(
    key: K,
    value: NotificationConfig[K],
  ) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      apply(await setNotifyConfig(draft))
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
      apply(await resetNotifyConfig())
      setSaved(false)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const runTest = async () => {
    setTesting(true)
    setError(null)
    setTestResult(null)
    try {
      const outcome = await testNotify()
      setTestResult(
        outcome.shown
          ? `toast shown — “${outcome.title}” for ${outcome.duration_s}s`
          : 'the platform reported the toast as not shown',
      )
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setTesting(false)
    }
  }

  return (
    <SettingsCard
      id="notify"
      title="Notifications"
      icon={<BellIcon className="size-4 text-tint" />}
      badge={
        <>
          <span
            className={`rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${
              status.enabled && status.capability.allowed
                ? 'border-status-ok/40 bg-status-ok/10 text-status-ok'
                : 'border-white/15 text-muted'
            }`}
          >
            {status.enabled ? 'on' : 'off'}
          </span>
          {!status.capability.allowed ? (
            <span
              className="rounded border border-danger/40 px-1.5 py-0.5 font-mono text-[10px] text-danger"
              title={status.capability.reason ?? 'notifications capability denied'}
            >
              blocked
            </span>
          ) : null}
          <span
            className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted"
            title="Windows toast notifications via the WinRT toast API"
          >
            {status.platform}
          </span>
        </>
      }
      hint={
        <>
          Lets the model raise Windows toast notifications (Phase 10): the{' '}
          <span className="text-ink">notify</span> tool and long-running jobs use them to get your
          attention. Toasts go through a stdlib-only PowerShell call — no dependencies — and the{' '}
          <span className="text-ink">notifications</span> capability is the hard gate. Changes apply
          when you press <span className="text-ink">Save</span>.
        </>
      }
      actions={
        <button
          type="button"
          onClick={() => {
            setLoading(true)
            void load()
          }}
          disabled={loading || busy !== null || testing}
          className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
            loading || busy !== null || testing
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
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Toast</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Enable notifications" hint="off = the notify tool answers 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="Notifications enabled"
              />
            </Row>
            <Row label="Sound" hint="play the default notification sound">
              <Toggle
                checked={config.sound}
                disabled={busy !== null}
                onChange={(value) => setField('sound', value)}
                label="Notification sound"
              />
            </Row>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Appearance</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="App name" hint="title prefix on every toast">
              <input
                value={config.app_name}
                disabled={busy !== null}
                placeholder="Luxion"
                onChange={(event) => setField('app_name', event.target.value)}
                className={TEXT_CLASS}
              />
            </Row>
            <Row label="On screen" hint="seconds (Windows clamps to 25)">
              <input
                type="number"
                value={String(config.default_duration_s ?? '')}
                min={3}
                max={25}
                step={1}
                disabled={busy !== null}
                onChange={(event) => setField('default_duration_s', Number(event.target.value))}
                className={NUM_CLASS}
              />
            </Row>
            <Row label="Cooldown" hint="minimum seconds between two toasts">
              <input
                type="number"
                value={String(config.cooldown_s ?? '')}
                min={0}
                max={60}
                step={1}
                disabled={busy !== null}
                onChange={(event) => setField('cooldown_s', Number(event.target.value))}
                className={NUM_CLASS}
              />
            </Row>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Capability</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">notifications — {status.capability.state}</p>
            <p className="font-mono text-[10px] text-muted/70">
              {status.capability.allowed
                ? 'the executor lets notify through'
                : (status.capability.reason ?? 'denied — grant it in Settings → Privacy')}
            </p>
          </div>
          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Test</p>
            <p className="font-mono text-[10px] text-muted/70">
              raise one real toast — the same path the tool uses
            </p>
            <button
              type="button"
              onClick={() => void runTest()}
              disabled={testing}
              className={`mt-2 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
                testing
                  ? 'cursor-wait text-muted'
                  : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
              }`}
            >
              {testing ? 'Sending…' : 'Send test'}
            </button>
            {testResult ? (
              <p className="mt-2 font-mono text-[10px] text-status-ok">{testResult}</p>
            ) : null}
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
            title="Drop notify.json so .env / built-in defaults win again"
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
