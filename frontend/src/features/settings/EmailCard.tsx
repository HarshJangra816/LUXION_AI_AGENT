import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, MailIcon, RefreshIcon, TrashIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  deleteEmailDraft,
  getEmailConfig,
  probeEmail,
  resetEmailConfig,
  setEmailConfig,
  type EmailConfig,
  type EmailConfigBundle,
} from '../../lib/email'

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
  'h-8 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

/** Human labels for the two probe legs the backend reports on. */
const LEG_LABEL: Record<string, string> = {
  smtp: 'SMTP (send)',
  imap: 'IMAP (read)',
}

export function EmailCard() {
  const [bundle, setBundle] = useState<EmailConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<EmailConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [probe, setProbe] = useState<Record<string, string> | null>(null)
  const [probing, setProbing] = useState(false)

  const apply = (data: EmailConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getEmailConfig(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getEmailConfig(controller.signal)
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
  const config: EmailConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status

  const setField = <K extends keyof EmailConfig>(key: K, value: EmailConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof EmailConfig, min: number, max: number, step: number) => (
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

  const text = (key: keyof EmailConfig, placeholder: string) => (
    <input
      value={String(config[key] ?? '')}
      disabled={busy !== null}
      placeholder={placeholder}
      onChange={(event) => setField(key, event.target.value as never)}
      className={TEXT_CLASS}
    />
  )

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      apply(await setEmailConfig(draft))
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
      apply(await resetEmailConfig())
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
      const result = await probeEmail()
      setProbe(result.results)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setProbing(false)
    }
  }

  const removeDraft = async (id: string) => {
    setBusy('draft')
    setError(null)
    try {
      await deleteEmailDraft(id)
      apply(await getEmailConfig())
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <SettingsCard
      id="email"
      title="Email"
      icon={<MailIcon className="size-4 text-tint" />}
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
          {status.smtp_configured ? (
            <span
              className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted"
              title="SMTP is fully addressed: host + sender set"
            >
              smtp
            </span>
          ) : null}
          {status.imap_configured ? (
            <span
              className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted"
              title="IMAP reading is available"
            >
              imap
            </span>
          ) : null}
        </>
      }
      hint={
        <>
          Lets the model compose, send and read mail through your own account — SMTP to send
          (smtplib), IMAP to read (imaplib), both stdlib (PRD §33.4). The password never enters
          Luxion's settings: it lives in <span className="text-ink">.env</span> as{' '}
          <span className="text-ink">LUXION_EMAIL__SMTP_PASSWORD</span> or in the env var you name
          below. Changes apply when you press <span className="text-ink">Save</span>.
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
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            SMTP (outgoing)
          </h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Enable email tools" hint="off = every email tool answers 'disabled'">
              <Toggle
                checked={config.enabled}
                disabled={busy !== null}
                onChange={(value) => setField('enabled', value)}
                label="Email enabled"
              />
            </Row>
            <Row label="SMTP host" hint="smtp.gmail.com · smtp.office365.com">
              {text('smtp_host', 'smtp.example.com')}
            </Row>
            <Row label="Port" hint="587 STARTTLS · 465 SSL">
              {num('smtp_port', 1, 65535, 1)}
            </Row>
            <Row label="Security">
              <select
                value={config.smtp_security}
                disabled={busy !== null}
                onChange={(event) =>
                  setField('smtp_security', event.target.value as EmailConfig['smtp_security'])
                }
                className={SELECT_CLASS}
              >
                <option value="starttls">starttls</option>
                <option value="ssl">ssl</option>
                <option value="none">none</option>
              </select>
            </Row>
            <Row label="Username" hint="empty = the From address">
              {text('smtp_username', 'you@example.com')}
            </Row>
            <Row label="Password env var" hint="name only — the secret stays in the environment">
              {text('smtp_password_env', 'MY_SMTP_PASS')}
            </Row>
          </div>
          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Password</p>
            <p className="font-mono text-[10px] text-muted/70">
              {status.password_configured
                ? status.password_env
                  ? 'resolved from the named env var'
                  : 'resolved from LUXION_EMAIL__SMTP_PASSWORD'
                : 'not configured — sending will refuse until it is set'}
            </p>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            Identity &amp; inbox
          </h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="From name">{text('from_name', 'Luxion')}</Row>
            <Row label="From address" hint="envelope sender + default login">
              {text('from_address', 'you@example.com')}
            </Row>
            <Row label="IMAP host" hint="empty = email_read is unavailable">
              {text('imap_host', 'imap.example.com')}
            </Row>
            <Row label="IMAP port" hint="993 is the SSL norm">
              {num('imap_port', 1, 65535, 1)}
            </Row>
            <Row label="Inbox read limit" hint="max messages email_read returns">
              {num('read_limit', 1, 50, 1)}
            </Row>
          </div>
          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Signature</p>
            <textarea
              value={config.signature}
              rows={2}
              disabled={busy !== null}
              placeholder="appended to plain-text bodies"
              onChange={(event) => setField('signature', event.target.value)}
              className="mt-1 w-full resize-none rounded-lg border border-white/15 bg-surface/70 px-2 py-1.5 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
            />
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            Connection
          </h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Network timeout" hint="seconds per SMTP/IMAP connection">
              {num('timeout_s', 5, 120, 1)}
            </Row>
          </div>
          <div className="mt-3 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
            <p className="text-xs text-ink">Servers</p>
            <p className="font-mono text-[10px] text-muted/70">
              reach both once — no mail is sent
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
              {probing ? 'Testing…' : 'Test servers'}
            </button>
            {probe ? (
              <ul className="mt-2 flex flex-col gap-1">
                {Object.entries(probe).map(([leg, result]) => (
                  <li
                    key={leg}
                    className="flex items-center justify-between gap-2 font-mono text-[10px]"
                  >
                    <span className="text-muted">{LEG_LABEL[leg] ?? leg}</span>
                    <span
                      className={
                        result.startsWith('ok')
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
      </div>

      <div className="mt-4">
        <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Drafts</h4>
        <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5">
          {bundle.drafts.length === 0 ? (
            <p className="text-xs text-muted">
              No drafts. The <span className="text-ink">email_draft</span> tool stores its output
              here until <span className="text-ink">email_send_draft</span> ships it — nothing is
              sent on draft alone.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {bundle.drafts.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-3 border-b border-white/8 pb-1.5 last:border-b-0 last:pb-0"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-xs text-ink">
                      {item.subject || '(no subject)'}
                    </span>
                    <span className="block truncate font-mono text-[10px] text-muted/70">
                      to {item.to.join(', ') || '—'} · {new Date(item.created_at).toLocaleString()}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => void removeDraft(item.id)}
                    disabled={busy !== null}
                    title={`Discard draft ${item.id}`}
                    className={`shrink-0 rounded border border-white/15 p-1.5 transition duration-200 ${
                      busy !== null
                        ? 'cursor-not-allowed text-muted/50'
                        : 'cursor-pointer text-muted hover:border-danger/50 hover:text-danger'
                    }`}
                  >
                    <TrashIcon className="size-3.5" />
                    <span className="sr-only">Discard draft</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
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
            title="Drop email.json so .env / built-in defaults win again"
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
