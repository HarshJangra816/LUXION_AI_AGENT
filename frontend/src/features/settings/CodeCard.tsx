import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, RefreshIcon, TerminalIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  getCodeConfig,
  resetCodeConfig,
  setCodeConfig,
  type CapabilityState,
  type CodeConfig,
  type CodeConfigBundle,
} from '../../lib/code'

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

/** Human wording for the `terminal` capability states. */
const CAPABILITY_LABEL: Record<CapabilityState, string> = {
  granted: 'allowed',
  denied: 'not allowed',
  blocked_by_os: 'blocked by windows',
  unavailable: 'unavailable',
  not_connected: 'not connected',
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

export function CodeCard() {
  const [bundle, setBundle] = useState<CodeConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<CodeConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getCodeConfig(signal)
      setBundle(data)
      setDraft({})
      setError(null)
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getCodeConfig(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setBundle(data)
        setDraft({})
        setError(null)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(messageOf(err))
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  if (!bundle) return null
  const config: CodeConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status

  const setField = <K extends keyof CodeConfig>(key: K, value: CodeConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof CodeConfig, min: number, max: number, step: number) => (
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
      const data = await setCodeConfig(draft)
      setBundle(data)
      setDraft({})
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
      const data = await resetCodeConfig()
      setBundle(data)
      setDraft({})
      setSaved(false)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SettingsCard
      id="coding"
      title="Coding agent"
      icon={<TerminalIcon className="size-4 text-tint" />}
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
          <span
            className={`max-w-[14rem] truncate rounded border px-1.5 py-0.5 font-mono text-[10px] ${
              status.git ? 'border-white/15 text-muted' : 'border-danger/30 text-danger'
            }`}
          >
            git {status.git ? 'ok' : 'missing'}
          </span>
          {status.github_cli ? (
            <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
              gh ok
            </span>
          ) : null}
        </>
      }
      hint={
        <>
          Lets the model work on code: analyze a repository, grep it, edit files, run commands,
          tests and installs, and use git and the GitHub CLI (PRD §34, §35). Turning this off
          makes every <span className="font-mono text-[11px]">code</span> tool answer{' '}
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

      <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Access</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Enable coding tools" hint="off = every code tool answers 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="Coding tools enabled"
              />
            </Row>
          </div>

          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Terminal consent</p>
            <p className="font-mono text-[10px] text-muted/70">
              the model may {CAPABILITY_LABEL[status.terminal_capability]} commands, tests and
              installs on this machine
              {status.terminal_capability_reason
                ? ` — ${status.terminal_capability_reason}`
                : ''}
            </p>
            <p className="mt-1 font-mono text-[10px] text-muted/60">
              grant or revoke it in Permissions &amp; capabilities below
            </p>
          </div>

          {status.workspace ? (
            <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
              <p className="text-xs text-ink">Project root</p>
              <p className="truncate font-mono text-[10px] text-muted/70" title={status.workspace}>
                {status.workspace}
              </p>
            </div>
          ) : null}
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Limits</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Command timeout" hint="seconds before a command is killed">
              {num('command_timeout_s', 5, 900, 15)}
            </Row>
            <Row label="Output limit" hint="characters of stdout+stderr the model sees">
              {num('max_output_chars', 1000, 200000, 1000)}
            </Row>
          </div>
          <p className="mt-2 font-mono text-[10px] text-muted/60">
            destructive commands are refused outright; API keys are stripped from every child
            process
          </p>
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
            title="Drop code.json so .env / built-in defaults win again"
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
