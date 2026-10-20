import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertIcon,
  CheckIcon,
  GaugeIcon,
  PaletteIcon,
  RefreshIcon,
  TypeIcon,
} from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
import {
  getLlmHealth,
  getLlmStatus,
  resetLlmProvider,
  setLlmProvider,
  type ContextStats,
  type LlmHealth,
  type LlmStatus,
} from '../../lib/chat'
import {
  ACCENT_PRESETS,
  MONO_FONTS,
  SIZES,
  UI_FONTS,
  useAppearance,
  type FontId,
  type MonoId,
  type SizeId,
} from '../../lib/appearance'
import { useAIState } from '../../lib/aiState'
import { MAX_BRIGHTNESS, MIN_BRIGHTNESS, useGraphics, type Quality } from '../../lib/graphics'
import {
  formatCost,
  formatTokens,
  getUsage,
  type ContextBudget,
  type UsageReport,
} from '../../lib/usage'

const QUALITY_COPY: Record<Quality, { title: string; detail: string; hint: string }> = {
  high: {
    title: 'High',
    detail: 'Full particle field, antialiasing, all blueprint detail rings',
    hint: 'discrete GPU',
  },
  medium: {
    title: 'Medium',
    detail: 'Reduced particles and glow layers, no antialiasing',
    hint: 'default · balanced',
  },
  low: {
    title: 'Low',
    detail: 'Minimal particles, coarse geometry, single glow layer',
    hint: 'integrated GPU',
  },
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-panel/70 p-4 backdrop-blur-md">
      <div className="text-xs uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-2 truncate font-mono text-sm text-ink" title={value}>
        {value}
      </div>
      <div className="mt-1 truncate text-[11px] text-muted/70" title={hint}>
        {hint ?? ' '}
      </div>
    </div>
  )
}

const COMPRESSION_COPY: Record<ContextStats['compression'], string> = {
  none: 'everything fit',
  dropped: 'older turns dropped',
  summary: 'older turns summarized',
}

const SEGMENTS: { label: keyof Pick<ContextStats, 'system_tokens' | 'summary_tokens' | 'history_tokens'>; className: string }[] =
  [
    { label: 'system_tokens', className: 'bg-tint/70' },
    { label: 'summary_tokens', className: 'bg-accent' },
    { label: 'history_tokens', className: 'bg-white/45' },
  ]

const SEGMENT_LABEL: Record<(typeof SEGMENTS)[number]['label'], string> = {
  system_tokens: 'System prompt',
  summary_tokens: 'Summary',
  history_tokens: 'History',
}

function ContextBar({ stats }: { stats: ContextStats }) {
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-white/10">
        {SEGMENTS.map((segment) => (
          <span
            key={segment.label}
            className={segment.className}
            style={{ width: `${(stats[segment.label] / stats.budget_tokens) * 100}%` }}
            title={`${SEGMENT_LABEL[segment.label]}: ${stats[segment.label].toLocaleString()} tok`}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        {SEGMENTS.map((segment) => (
          <span key={segment.label} className="inline-flex items-center gap-1.5">
            <span className={`size-2 rounded-full ${segment.className}`} />
            {SEGMENT_LABEL[segment.label]}
            <span className="font-mono text-ink">{formatTokens(stats[segment.label])}</span>
          </span>
        ))}
        <span className="font-mono text-muted/70">
          {formatTokens(stats.estimated_tokens)} / {formatTokens(stats.budget_tokens)} used
        </span>
      </div>
    </div>
  )
}

/**
 * One installed adapter. Inactive cards are the tap target (whole card is a
 * button); the active card shows its state and hosts `children` (the model
 * editor) instead — a button may not contain form controls.
 */
function AdapterCard({
  provider,
  active,
  disabled,
  onSelect,
  children,
}: {
  provider: LlmStatus['available_providers'][number]
  active: boolean
  disabled: boolean
  onSelect: () => void
  children?: ReactNode
}) {
  const head = (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate text-sm text-ink">{provider.label}</div>
        <div className="font-mono text-[11px] text-muted/70">{provider.id}</div>
      </div>
      <span className="shrink-0 rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
        {provider.local ? 'local' : 'cloud'}
      </span>
    </div>
  )

  if (active) {
    return (
      <li className="rounded-xl border border-tint/50 bg-tint/12 p-4 backdrop-blur-md transition duration-200">
        {head}
        <div className="mt-3 border-t border-white/10 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded border border-tint/40 bg-tint/10 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.16em] text-tint uppercase">
              <CheckIcon className="size-3" />
              active
            </span>
            <span className="font-mono text-[10px] text-muted/70">tap another adapter to switch</span>
          </div>
          {children}
        </div>
      </li>
    )
  }

  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        disabled={disabled}
        className={`w-full cursor-pointer rounded-xl border border-white/10 bg-panel/70 p-4 text-left backdrop-blur-md transition duration-200 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60 ${
          disabled ? '' : 'hover:border-white/30'
        }`}
      >
        {head}
        <span className="mt-2 block font-mono text-[10px] tracking-[0.16em] text-muted/70 uppercase">
          tap to activate
        </span>
      </button>
    </li>
  )
}

export function SettingsPage() {
  const [status, setStatus] = useState<LlmStatus | null>(null)
  const [health, setHealth] = useState<LlmHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [probing, setProbing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [usage, setUsage] = useState<UsageReport | null>(null)
  const [usageLoading, setUsageLoading] = useState(true)
  const [refreshingUsage, setRefreshingUsage] = useState(false)
  const [usageError, setUsageError] = useState<string | null>(null)
  /** Adapter id being applied (or `'__reset__'`), `null` when idle. */
  const [switching, setSwitching] = useState<string | null>(null)
  /** Failure of the last adapter switch — shown next to the adapter list. */
  const [switchError, setSwitchError] = useState<string | null>(null)
  /** Unsaved model edits, keyed by the adapter they belong to. */
  const [modelDraft, setModelDraft] = useState<{ provider: string; value: string } | null>(null)
  const { pulse } = useAIState()
  const {
    quality,
    setQuality,
    profile,
    reducedMotion,
    brightness,
    setBrightness,
  } = useGraphics()
  const { font, setFont, mono, setMono, size, setSize, accentValue, setAccentValue, accent } =
    useAppearance()

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getLlmStatus(signal)
      setStatus(data)
      setError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setError(messageOf(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  const probe = useCallback(async () => {
    setProbing(true)
    try {
      setHealth(await getLlmHealth())
      setError(null)
      pulse('success', 1300)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setProbing(false)
    }
  }, [pulse])

  /** Apply a provider change and refresh every provider-derived view. */
  const runProviderChange = useCallback(
    async (busy: string, change: () => Promise<LlmStatus>) => {
      setSwitching(busy)
      try {
        const next = await change()
        setStatus(next)
        setModelDraft(null)
        setHealth(null) // reachability belonged to the previous adapter
        setSwitchError(null)
        pulse('success', 1300)
      } catch (caught) {
        setSwitchError(messageOf(caught))
        pulse('error', 1600)
      } finally {
        setSwitching(null)
      }
    },
    [pulse],
  )

  /** Whatever the active adapter should show — unsaved edits win. */
  const currentModel = status?.model ?? ''
  const modelValue =
    modelDraft && modelDraft.provider === status?.provider ? modelDraft.value : currentModel

  const selectAdapter = (provider: string) => {
    if (switching !== null || !status || status.provider === provider) return
    void runProviderChange(provider, () => setLlmProvider(provider))
  }

  const saveModel = () => {
    if (switching !== null || !status || modelValue === status.model) return
    void runProviderChange(status.provider, () => setLlmProvider(status.provider, modelValue))
  }

  const resetAdapters = () => {
    if (switching !== null) return
    void runProviderChange('__reset__', () => resetLlmProvider())
  }

  const loadUsage = useCallback(async (signal?: AbortSignal) => {
    try {
      setUsage(await getUsage(signal))
      setUsageError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setUsageError(messageOf(caught))
    } finally {
      setUsageLoading(false)
    }
  }, [])

  const refreshUsage = useCallback(async () => {
    setRefreshingUsage(true)
    try {
      setUsage(await getUsage())
      setUsageError(null)
      pulse('success', 1200)
    } catch (caught) {
      setUsageError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setRefreshingUsage(false)
    }
  }, [pulse])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void loadUsage(controller.signal)
    return () => controller.abort()
  }, [loadUsage])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const budget: ContextBudget | null = usage?.budget ?? null
  const totals = usage?.totals ?? null
  const spend = totals ? formatCost(totals.cost_usd) : null
  const lastContext = usage?.recent_turns[0]?.context ?? null
  const recentTurns = (usage?.recent_turns ?? []).slice(0, 5)

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6 md:p-8">
      <SettingsCard
        id="provider"
        title="AI provider"
        defaultOpen
        hint={
          <>
            Tap an adapter under <span className="text-ink">Installed provider adapters</span> to
            switch — it applies immediately and survives a restart. Defaults come from{' '}
            <code className="font-mono text-muted">LUXION_LLM__*</code> in{' '}
            <code className="font-mono text-muted">.env</code>.
          </>
        }
        actions={
          <button
            type="button"
            onClick={() => void probe()}
            disabled={probing}
            className={`flex items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
              probing
                ? 'cursor-wait text-muted'
                : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
            }`}
          >
            <RefreshIcon className={`size-3.5 ${probing ? 'animate-spin' : ''}`} />
            {probing ? 'Probing…' : 'Test connection'}
          </button>
        }
      >
        {error ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Field
            label="Provider"
            value={status ? status.label : '—'}
            hint={status ? status.provider : loading ? 'loading…' : 'unavailable'}
          />
          <Field
            label="Model"
            value={status ? status.model || '(auto: first reported)' : '—'}
            hint={status ? 'remembered per adapter' : ' '}
          />
          <Field
            label="Base URL"
            value={status ? status.base_url : '—'}
            hint={status ? `timeout ${status.request_timeout_s}s` : ' '}
          />
          <Field
            label="Sampling"
            value={status ? `${status.temperature} · max ${status.max_tokens}` : '—'}
            hint="temperature / max_tokens"
          />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-panel/70 p-5 backdrop-blur-md">
            <h3 className="text-sm font-semibold text-ink">Credentials</h3>
            <dl className="mt-3 flex flex-col gap-2 text-xs">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted">API key</dt>
                <dd className="font-mono text-ink">
                  {status
                    ? status.api_key_configured
                      ? 'configured'
                      : 'not set'
                    : '—'}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted">Key source</dt>
                <dd className="font-mono text-ink">{status?.api_key_env || 'LUXION_LLM__API_KEY'}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted">System prompt</dt>
                <dd className="font-mono text-ink">
                  {status ? (status.uses_default_system_prompt ? 'default' : 'custom') : '—'}
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-xl border border-white/10 bg-panel/70 p-5 backdrop-blur-md">
            <h3 className="text-sm font-semibold text-ink">Reachability</h3>
            {!health ? (
              <p className="mt-3 text-xs text-muted">
                Not probed yet — run <span className="text-ink">Test connection</span>.
              </p>
            ) : (
              <dl className="mt-3 flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Status</dt>
                  <dd className="flex items-center gap-2 font-mono text-ink">
                    <span
                      className={`inline-block size-2 rounded-full ${health.ok ? 'bg-status-ok' : 'bg-danger'}`}
                    />
                    {health.ok ? 'reachable' : 'unreachable'}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-muted">Latency</dt>
                  <dd className="font-mono text-ink">{health.latency_ms ?? '—'} ms</dd>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <dt className="shrink-0 text-muted">Models</dt>
                  <dd className="max-w-56 truncate text-right font-mono text-ink" title={health.models.join(', ')}>
                    {health.models.length ? health.models.join(', ') : 'none reported'}
                  </dd>
                </div>
                {health.error ? (
                  <div className="rounded border border-danger/30 bg-danger/10 px-2 py-1.5 text-danger">
                    {health.error}
                  </div>
                ) : null}
              </dl>
            )}
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">Installed provider adapters</h3>
            <p className="mt-1.5 text-xs text-muted">
              Tap an adapter to make it active. The choice is written to{' '}
              <code className="font-mono text-muted">llm_provider.json</code> in the data directory
              and applied without a restart.
            </p>
          </div>
          <button
            type="button"
            onClick={() => resetAdapters()}
            disabled={switching !== null}
            className={`shrink-0 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
              switching !== null
                ? 'cursor-wait text-muted'
                : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
            }`}
          >
            {switching === '__reset__' ? 'Resetting…' : 'Reset to .env'}
          </button>
        </div>

        {switchError ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{switchError}</span>
          </div>
        ) : null}

        <ul className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(status?.available_providers ?? []).map((provider) => {
            const active = status?.provider === provider.id
            return (
              <AdapterCard
                key={provider.id}
                provider={provider}
                active={active}
                disabled={switching !== null}
                onSelect={() => selectAdapter(provider.id)}
              >
                {active ? (
                  <>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <label
                        htmlFor="lux-provider-model"
                        className="font-mono text-[10px] tracking-[0.16em] text-muted uppercase"
                      >
                        Model
                      </label>
                      <input
                        id="lux-provider-model"
                        list="lux-model-suggestions"
                        value={modelValue}
                        disabled={switching !== null}
                        onChange={(event) =>
                          setModelDraft({ provider: provider.id, value: event.target.value })
                        }
                        placeholder="auto · first model reported"
                        className="min-w-0 flex-1 rounded-lg border border-white/15 bg-surface/70 px-2.5 py-1.5 font-mono text-xs text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                      />
                      <button
                        type="button"
                        onClick={() => saveModel()}
                        disabled={switching !== null || modelValue === currentModel}
                        className={`shrink-0 rounded-lg border border-white/15 px-2.5 py-1.5 text-xs transition duration-200 focus:border-tint/60 focus:outline-none ${
                          switching !== null || modelValue === currentModel
                            ? 'cursor-default text-muted/50'
                            : 'cursor-pointer text-ink hover:border-tint/60 hover:text-tint'
                        }`}
                      >
                        {switching === provider.id ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                    <datalist id="lux-model-suggestions">
                      {(health?.models ?? []).map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                    <p className="mt-1.5 text-[10px] text-muted/60">
                      {health?.models.length
                        ? `${health.models.length} model(s) reported by this adapter — type to pick one.`
                        : 'Leave empty to use the first model the adapter reports. Run Test connection to suggest installed models.'}
                    </p>
                  </>
                ) : null}
              </AdapterCard>
            )
          })}
        </ul>
      </SettingsCard>

      <SettingsCard
        id="context"
        title="Context & usage"
        hint={
          <>
            How much of the window each turn sends, plus lifetime token spend. Budgets come from{' '}
            <code className="font-mono text-muted">LUXION_CONTEXT__*</code> in{' '}
            <code className="font-mono text-muted">.env</code>.
          </>
        }
        actions={
          <button
            type="button"
            onClick={() => void refreshUsage()}
            disabled={refreshingUsage || usageLoading}
            className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
              refreshingUsage || usageLoading
                ? 'cursor-wait text-muted'
                : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
            }`}
          >
            <RefreshIcon className={`size-3.5 ${refreshingUsage ? 'animate-spin' : ''}`} />
            {refreshingUsage ? 'Refreshing…' : 'Refresh'}
          </button>
        }
      >
        {usageError ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{usageError}</span>
          </div>
        ) : null}

        {!usage && usageLoading ? (
          <p className="mt-4 text-xs text-muted">Loading usage…</p>
        ) : null}

        {budget && totals ? (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field
                label="Window"
                value={formatTokens(budget.total)}
                hint="TOTAL_BUDGET_TOKENS"
              />
              <Field label="Reserve" value={formatTokens(budget.reserve)} hint="absorbs estimate error" />
              <Field label="Reply headroom" value={formatTokens(budget.response)} hint="llm.max_tokens" />
              <Field
                label="Spendable"
                value={formatTokens(budget.spendable)}
                hint="system + summary + history"
              />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field
                label="Messages"
                value={totals.messages.toLocaleString()}
                hint={`${totals.conversations} conversations`}
              />
              <Field label="Tokens in" value={formatTokens(totals.tokens_in)} hint="prompt tokens sent" />
              <Field label="Tokens out" value={formatTokens(totals.tokens_out)} hint="completion tokens" />
              <Field
                label="Spend"
                value={spend ?? 'not reported'}
                hint={spend ? 'provider-reported' : 'provider reports no cost'}
              />
            </div>

            <p className="mt-3 font-mono text-[11px] text-muted/70">
              keep last {budget.keep_recent_messages} · summary{' '}
              {budget.summary_enabled ? 'on' : 'off'} · load newest {budget.max_history_messages}{' '}
              messages
            </p>

            {lastContext ? (
              <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-xs uppercase tracking-wider text-muted">Last turn</h4>
                  <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
                    {COMPRESSION_COPY[lastContext.compression]}
                    {lastContext.truncated ? ' · clipped' : ''}
                  </span>
                </div>
                <div className="mt-3">
                  <ContextBar stats={lastContext} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] sm:grid-cols-4">
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted">Sent</dt>
                    <dd className="font-mono text-ink">{lastContext.messages_sent} msgs</dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted">Kept</dt>
                    <dd className="font-mono text-ink">
                      {lastContext.history_sent}/{lastContext.history_available}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted">Dropped</dt>
                    <dd className="font-mono text-ink">{lastContext.history_dropped}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted">Summarized</dt>
                    <dd className="font-mono text-ink">{lastContext.summarized}</dd>
                  </div>
                </dl>
              </div>
            ) : null}

            <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 p-4">
              <h4 className="text-xs uppercase tracking-wider text-muted">Recent turns</h4>
              {recentTurns.length ? (
                <dl className="mt-3 flex flex-col gap-1.5 text-[11px]">
                  {recentTurns.map((turn) => {
                    const cost = formatCost(turn.cost_usd)
                    return (
                      <div
                        key={turn.message_id}
                        className="flex items-center justify-between gap-3"
                      >
                        <dt className="truncate text-muted">{turn.title ?? 'Untitled'}</dt>
                        <dd className="shrink-0 font-mono text-ink">
                          {formatTokens(turn.tokens_in ?? 0)}→
                          {formatTokens(turn.tokens_out ?? 0)} tok{cost ? ` · ${cost}` : ''}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
              ) : (
                <p className="mt-2 text-[11px] text-muted/70">No assistant turns yet.</p>
              )}
            </div>
          </>
        ) : null}
      </SettingsCard>

      <SettingsCard
        id="appearance"
        title="Appearance"
        icon={<TypeIcon className="size-4 text-tint" />}
        hint="Fonts, type scale and accent colour for the whole interface. Stored in this browser and applied immediately."
      >
        <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-2">
          <fieldset>
            <legend className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
              Interface font
            </legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {UI_FONTS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setFont(option.id as FontId)}
                  style={{ fontFamily: option.stack }}
                  className={`cursor-pointer rounded-lg border px-3 py-2 text-left transition duration-200 ${
                    font === option.id
                      ? 'border-tint/60 bg-tint/12'
                      : 'border-white/10 bg-panel/70 hover:border-white/25'
                  }`}
                >
                  <span className="block truncate text-sm text-ink">{option.label}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-muted/80">
                    {option.hint}
                  </span>
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
              Display font
            </legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {MONO_FONTS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setMono(option.id as MonoId)}
                  style={{ fontFamily: option.stack }}
                  className={`cursor-pointer rounded-lg border px-3 py-2 text-left transition duration-200 ${
                    mono === option.id
                      ? 'border-tint/60 bg-tint/12'
                      : 'border-white/10 bg-panel/70 hover:border-white/25'
                  }`}
                >
                  <span className="block truncate text-sm text-ink">{option.label}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-muted/80">
                    {option.hint}
                  </span>
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted/80">
              Used by headings, the HUD and code blocks.
            </p>
          </fieldset>
        </div>

        <fieldset className="mt-5">
          <legend className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            Text size
          </legend>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SIZES.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setSize(option.id as SizeId)}
                className={`cursor-pointer rounded-lg border px-3 py-2 text-left transition duration-200 ${
                  size === option.id
                    ? 'border-tint/60 bg-tint/12'
                    : 'border-white/10 bg-panel/70 hover:border-white/25'
                }`}
              >
                <span className="block text-sm text-ink">{option.label}</span>
                <span className="mt-0.5 block font-mono text-[10px] text-muted/80">
                  {option.px}px · {option.hint}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted/80">
            Scales every text size in the app — the 3D core keeps its own fixed layout.
          </p>
        </fieldset>

        <fieldset className="mt-5">
          <legend className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            <span className="inline-flex items-center gap-1.5">
              <PaletteIcon className="size-3.5" />
              Accent colour
            </span>
          </legend>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {ACCENT_PRESETS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setAccentValue(option.id)}
                className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition duration-200 ${
                  accentValue === option.id
                    ? 'border-tint/60 bg-tint/12 text-ink'
                    : 'border-white/10 bg-panel/70 text-muted hover:border-white/25'
                }`}
              >
                <span
                  className="size-3 rounded-full ring-1 ring-white/30"
                  style={{ backgroundColor: option.tint }}
                />
                {option.label}
              </button>
            ))}

            <label
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition duration-200 ${
                accentValue.startsWith('#')
                  ? 'border-tint/60 bg-tint/12 text-ink'
                  : 'border-white/10 bg-panel/70 text-muted hover:border-white/25'
              }`}
            >
              <input
                type="color"
                value={accentValue.startsWith('#') ? accentValue : accent.tint}
                onChange={(event) => setAccentValue(event.target.value)}
                className="size-5 cursor-pointer rounded-full border-0 bg-transparent p-0"
                aria-label="Custom accent colour"
              />
              Custom
            </label>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-surface/60 px-3 py-2.5 text-xs">
            <span className="text-tint">tint text</span>
            <span className="rounded border border-tint/40 px-1.5 py-0.5 font-mono text-[10px] text-tint uppercase">
              hud label
            </span>
            <span className="rounded bg-accent px-2.5 py-1 font-semibold text-on-accent">
              primary action
            </span>
            <span className="inline-flex items-center gap-1.5 text-muted">
              <span className="size-2 rounded-full bg-status-ok" />
              status stays green
            </span>
          </div>
        </fieldset>
      </SettingsCard>

      <SettingsCard
        id="graphics"
        title="Graphics"
        icon={<GaugeIcon className="size-4 text-tint" />}
        hint="Rendering preset for the 3D core. Saved in this browser, applied immediately."
        actions={
          <span className="font-mono text-[11px] text-muted/70">
            {profile.particles} particles · {profile.rings} rings · DPR{' '}
            {profile.dpr[0]}–{profile.dpr[1]}
          </span>
        }
      >
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {(['high', 'medium', 'low'] as Quality[]).map((option) => {
            const active = quality === option
            const copy = QUALITY_COPY[option]
            return (
              <button
                key={option}
                type="button"
                onClick={() => setQuality(option)}
                className={`cursor-pointer rounded-xl border p-4 text-left transition duration-200 ${
                  active
                    ? 'border-tint/55 bg-tint/12'
                    : 'border-white/10 bg-panel/70 hover:border-white/25'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs tracking-[0.18em] text-ink uppercase">
                    {copy.title}
                  </span>
                  <span
                    className={`pointer-events-none size-2.5 rounded-full border transition duration-200 ${
                      active ? 'border-tint bg-tint' : 'border-white/30 bg-transparent'
                    }`}
                  />
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-muted">{copy.detail}</p>
                <p className="mt-2 font-mono text-[10px] text-muted/60 uppercase">{copy.hint}</p>
              </button>
            )
          })}
        </div>

        <div className="mt-5 border-t border-white/10 pt-4">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor="luxion-brightness" className="text-xs text-muted">
              Background brightness
            </label>
            <span className="font-mono text-xs text-tint">
              {Math.round(brightness * 100)}%
            </span>
          </div>
          <input
            id="luxion-brightness"
            type="range"
            min={MIN_BRIGHTNESS}
            max={MAX_BRIGHTNESS}
            step={0.05}
            value={brightness}
            onChange={(event) => setBrightness(Number(event.target.value))}
            className="mt-2 w-full cursor-pointer accent-tint"
          />
          <p className="mt-1.5 text-[11px] text-muted/80">
            Lowers the core's glow so text stays readable over it.
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/10 pt-4 text-[11px] text-muted">
          <span className="font-mono tracking-[0.16em] uppercase">
            prefers-reduced-motion: {reducedMotion ? 'reduce' : 'no-preference'}
          </span>
          <span>
            {reducedMotion
              ? 'The core is rendered but paused; only your own pulses animate.'
              : 'Full multi-layer rotation and pointer parallax are active.'}
          </span>
        </div>
      </SettingsCard>
    </div>
  )
}
