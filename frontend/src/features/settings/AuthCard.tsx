import { useCallback, useEffect, useState } from 'react'
import {
  AlertIcon,
  CameraIcon,
  MicIcon,
  RefreshIcon,
  ShieldCheckIcon,
  TrashIcon,
} from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  deleteAuthProfile,
  enrollAuth,
  getAuthConfig,
  listAuthProfiles,
  resetAuthConfig,
  setAuthConfig,
  verifyAuth,
  type AuthConfig,
  type AuthConfigBundle,
  type AuthMode,
  type AuthProfiles,
  type Modality,
} from '../../lib/auth'

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
        {hint ? <span className="block font-mono text-[10px] text-muted/70">{hint}</span> : null}
      </span>
      {children}
    </label>
  )
}

const NUM_CLASS =
  'h-8 w-24 shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 text-right font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

const MODE_LABEL: Record<AuthMode, string> = {
  disabled: 'Disabled',
  voice_only: 'Voice only',
  face_only: 'Face only',
  voice_face: 'Voice + Face',
}

/** Which modalities a mode enables — PRD §28's four-state box. */
const MODE_MODALITIES: Record<AuthMode, Modality[]> = {
  disabled: [],
  voice_only: ['voice'],
  face_only: ['face'],
  voice_face: ['voice', 'face'],
}

export function AuthCard() {
  const [bundle, setBundle] = useState<AuthConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<AuthConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [profiles, setProfiles] = useState<AuthProfiles | null>(null)
  const [working, setWorking] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [names, setNames] = useState<Record<Modality, string>>({ voice: '', face: '' })

  const apply = (data: AuthConfigBundle) => {
    setBundle(data)
    setDraft({})
    setError(null)
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      apply(await getAuthConfig(signal))
      setProfiles(await listAuthProfiles(signal))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    Promise.all([getAuthConfig(signal), listAuthProfiles(signal)])
      .then(([data, list]) => {
        if (signal.aborted) return
        apply(data)
        setProfiles(list)
      })
      .catch((err: unknown) => {
        if (signal.aborted) return
        setError(messageOf(err))
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [])

  const refreshProfiles = useCallback(async () => {
    try {
      setProfiles(await listAuthProfiles())
    } catch {
      // the profile list is secondary — never surface it as a card error
    }
  }, [])

  if (!bundle) return null
  const config: AuthConfig = { ...bundle.config, ...draft }
  const dirty = Object.keys(draft).length > 0
  const status = bundle.status
  const allowed = MODE_MODALITIES[config.mode]

  const setField = <K extends keyof AuthConfig>(key: K, value: AuthConfig[K]) => {
    setSaved(false)
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const num = (key: keyof AuthConfig, min: number, max: number, step: number) => (
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
      apply(await setAuthConfig(draft))
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
      apply(await resetAuthConfig())
      setSaved(false)
      setOutcome(null)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(null)
    }
  }

  const capture = async (modality: Modality, name: string, isEnroll: boolean) => {
    const clean = name.trim()
    const label = `${modality}-${isEnroll ? 'enroll' : 'verify'}-${clean}`
    setWorking(label)
    setError(null)
    setOutcome(null)
    try {
      if (isEnroll) {
        const result = await enrollAuth({ modality, name: clean })
        setOutcome(result.message)
      } else {
        const result = await verifyAuth({ modality, name: clean || undefined })
        setOutcome(result.message)
      }
      await refreshProfiles()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setWorking(null)
    }
  }

  const forget = async (modality: Modality, name: string) => {
    const label = `delete-${modality}-${name}`
    setWorking(label)
    setError(null)
    try {
      await deleteAuthProfile(modality, name)
      await refreshProfiles()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setWorking(null)
    }
  }

  const badge = status.biometrics.allowed ? (
    <span className="rounded border border-status-ok/40 bg-status-ok/10 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-status-ok uppercase">
      granted
    </span>
  ) : (
    <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-muted uppercase">
      off
    </span>
  )

  return (
    <SettingsCard
      id="auth"
      title="Authentication"
      icon={<ShieldCheckIcon className="size-4 text-tint" />}
      badge={badge}
      hint={
        <>
          A voice or face <span className="text-ink">second factor</span> (PRD §27/§28): enroll a
          profile, then let Luxion check <span className="text-ink">who said it</span> or{' '}
          <span className="text-ink">who is on camera</span> before a sensitive action. This is{' '}
          <span className="text-ink">not</span> speech recognition — that answers what was said;
          this answers who said it. The templates stay on this machine. Nothing runs until the{' '}
          <span className="text-ink">biometrics</span> capability is granted (it ships off).
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
        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Policy</h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="Security mode" hint="PRD §28: which factors are in play">
              <select
                value={config.mode}
                disabled={busy !== null}
                onChange={(event) => setField('mode', event.target.value as AuthMode)}
                className="h-8 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
              >
                {(Object.keys(MODE_LABEL) as AuthMode[]).map((value) => (
                  <option key={value} value={value}>
                    {MODE_LABEL[value]}
                  </option>
                ))}
              </select>
            </Row>
            <Row label="Voice clip" hint="seconds of speech to capture">
              {num('voice_duration_s', 1, 15, 0.5)}
            </Row>
            <Row label="Voice threshold" hint="1/(1+mean DTW cost); higher = stricter">
              {num('voice_threshold', 0, 1, 0.05)}
            </Row>
            <Row label="Face threshold" hint="SFace cosine; higher = stricter">
              {num('face_threshold', 0, 1, 0.05)}
            </Row>
            <Row label="Max profiles" hint="PRD §27/§28 cap">
              {num('max_profiles', 1, 5, 1)}
            </Row>
          </div>
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            Access & readiness
          </h4>
          <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
            <Row label="biometrics capability" hint={status.biometrics.reason}>
              <span
                className={`font-mono text-[10px] ${
                  status.biometrics.allowed ? 'text-status-ok' : 'text-danger'
                }`}
              >
                {status.biometrics.allowed ? 'granted' : 'off'}
              </span>
            </Row>
            <Row label="Microphone" hint={status.microphone.reason}>
              <MicIcon
                className={`size-4 ${status.microphone.allowed ? 'text-status-ok' : 'text-muted/50'}`}
              />
            </Row>
            <Row label="Camera" hint={status.camera.reason}>
              <CameraIcon
                className={`size-4 ${status.camera.allowed ? 'text-status-ok' : 'text-muted/50'}`}
              />
            </Row>
            <Row label="OpenCV / face API" hint="import checks — never opens a device here">
              <span className="flex items-center gap-2 font-mono text-[10px] text-muted">
                <span className={status.opencv_available ? 'text-status-ok' : 'text-muted/70'}>
                  {status.opencv_available ? 'opencv ok' : 'opencv missing'}
                </span>
                <span className="text-white/20">·</span>
                <span className={status.face_api ? 'text-status-ok' : 'text-muted/70'}>
                  {status.face_api ? 'face ok' : 'face missing'}
                </span>
              </span>
            </Row>
            <Row label="Face models" hint="downloaded once on first use, then offline">
              <span
                className={`font-mono text-[10px] ${
                  status.models_ready ? 'text-status-ok' : 'text-warning'
                }`}
              >
                {status.models_ready
                  ? 'ready'
                  : `${Object.values(status.models).filter(Boolean).length}/${bundle.catalog.models.length} fetched`}
              </span>
            </Row>
          </div>
          {!status.biometrics.allowed ? (
            <p className="mt-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[11px] text-warning">
              Grant the <span className="text-ink">biometrics</span> capability in Tools →
              Permissions &amp; capabilities. Even with a mode above, nothing runs until you do.
            </p>
          ) : null}
        </div>

        <div>
          <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">Profiles</h4>
          {(['voice', 'face'] as Modality[]).map((modality) => {
            const enabled = allowed.includes(modality)
            const list = profiles?.[modality] ?? []
            return (
              <div
                key={modality}
                className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-2.5"
              >
                <p className="flex items-center justify-between text-xs text-ink">
                  <span className="flex items-center gap-1.5">
                    {modality === 'voice' ? (
                      <MicIcon className="size-3.5 text-tint" />
                    ) : (
                      <CameraIcon className="size-3.5 text-tint" />
                    )}
                    {modality === 'voice' ? 'Voiceprint' : 'Faceprint'}
                  </span>
                  <span className="font-mono text-[10px] text-muted">
                    {list.length}/{config.max_profiles}
                  </span>
                </p>
                {list.length ? (
                  <ul className="mt-2 space-y-1">
                    {list.map((profile) => (
                      <li
                        key={profile.name}
                        className="flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-surface/70 px-2 py-1"
                      >
                        <span className="min-w-0 font-mono text-[11px] text-ink">
                          {profile.name}
                        </span>
                        <button
                          type="button"
                          onClick={() => void forget(modality, profile.name)}
                          disabled={working !== null}
                          title={`Forget '${profile.name}'`}
                          className="cursor-pointer rounded border border-white/15 p-1 text-muted transition duration-200 hover:border-danger/50 hover:text-danger disabled:cursor-wait disabled:opacity-50"
                        >
                          <TrashIcon className="size-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 font-mono text-[10px] text-muted/70">
                    {enabled ? 'no profiles yet' : 'this factor is off in the mode above'}
                  </p>
                )}
                <input
                  value={names[modality]}
                  placeholder="profile name"
                  disabled={working !== null}
                  onChange={(event) =>
                    setNames((prev) => ({ ...prev, [modality]: event.target.value }))
                  }
                  className="mt-2 h-8 w-full shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                />
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => void capture(modality, names[modality], true)}
                    disabled={
                      !enabled ||
                      !status.biometrics.allowed ||
                      working !== null ||
                      !names[modality].trim()
                    }
                    className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                      !enabled ||
                      !status.biometrics.allowed ||
                      working !== null ||
                      !names[modality].trim()
                        ? 'cursor-not-allowed border-white/10 text-muted/50'
                        : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
                    }`}
                  >
                    {working === `${modality}-enroll-${names[modality].trim()}` ? '…' : 'Enroll'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void capture(modality, names[modality], false)}
                    disabled={!enabled || !status.biometrics.allowed || working !== null}
                    title="Check a fresh clip/frame; leave the name empty to find out who it is"
                    className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                      !enabled || !status.biometrics.allowed || working !== null
                        ? 'cursor-not-allowed border-white/10 text-muted/50'
                        : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
                    }`}
                  >
                    {working === `${modality}-verify-${names[modality].trim()}` ? '…' : 'Verify'}
                  </button>
                </div>
              </div>
            )
          })}
          {outcome ? (
            <p className="mt-2 rounded-lg border border-white/10 bg-surface/70 px-2 py-1.5 text-[11px] whitespace-pre-wrap text-ink">
              {outcome}
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-[10px] text-muted/70">
          {dirty
            ? 'unsaved changes'
            : saved
              ? 'saved — the next check uses the new settings'
              : 'settings match the saved state'}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={resetAll}
            disabled={busy !== null}
            title="Drop biometrics.json so .env / built-in defaults win again"
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
