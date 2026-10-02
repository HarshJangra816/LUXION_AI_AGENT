import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertIcon,
  CheckIcon,
  GaugeIcon,
  PaletteIcon,
  RefreshIcon,
  ShieldIcon,
  TerminalIcon,
  TypeIcon,
} from '../../components/icons'
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
  capabilityAction,
  getCapabilities,
  STATE_CLASS,
  STATE_LABEL,
  type CalendarSource,
  type CapabilityActionBody,
  type CapabilityReport,
} from '../../lib/capabilities'
import {
  clearPermissions,
  getToolCatalog,
  getToolLog,
  setPermission,
  type PermissionLevel,
  type ToolCatalog,
  type ToolInfo,
  type ToolLogEntry,
  type ToolRisk,
} from '../../lib/tools'
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

const RISK_CLASS: Record<ToolRisk, string> = {
  low: 'border-status-ok/40 bg-status-ok/10 text-status-ok',
  medium: 'border-warning/40 bg-warning/10 text-warning',
  high: 'border-danger/40 bg-danger/10 text-danger',
  critical: 'border-danger/60 bg-danger/20 text-danger',
}

const PERMISSION_OPTIONS: { value: PermissionLevel | ''; label: string }[] = [
  { value: '', label: 'Autonomy default' },
  { value: 'allow', label: 'Allow' },
  { value: 'confirm', label: 'Ask first' },
  { value: 'deny', label: 'Deny' },
]

const RESULT_CLASS: Record<ToolLogEntry['result'], string> = {
  success: 'text-status-ok',
  error: 'text-danger',
  denied: 'text-danger',
  timeout: 'text-warning',
  invalid_args: 'text-warning',
}

function RiskBadge({ risk }: { risk: ToolRisk }) {
  return (
    <span
      className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${RISK_CLASS[risk]}`}
    >
      {risk}
    </span>
  )
}

/** One tool row: what it does, how risky it is, and what the user chose. */
function ToolRow({
  tool,
  busy,
  onChange,
}: {
  tool: ToolInfo
  busy: boolean
  onChange: (name: string, level: PermissionLevel | null) => void
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/8 py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-ink">{tool.name}</span>
          <RiskBadge risk={tool.risk} />
          {tool.read_only ? (
            <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted uppercase">
              read-only
            </span>
          ) : null}
          {tool.requires ? (
            <span
              className="rounded border border-tint/40 bg-tint/10 px-1.5 py-0.5 font-mono text-[10px] text-tint"
              title={`needs the ${tool.requires} capability (hard gate, PRD §39)`}
            >
              {tool.requires}
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted">{tool.description}</p>
        <p className="mt-1 font-mono text-[10px] text-muted/60" title={tool.permission_reason}>
          {tool.permission_reason}
        </p>
      </div>
      <select
        value={tool.override ?? ''}
        disabled={busy}
        onChange={(event) =>
          onChange(tool.name, event.target.value === '' ? null : (event.target.value as PermissionLevel))
        }
        aria-label={`Permission for ${tool.name}`}
        className={`h-8 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60 ${
          tool.permission === 'deny' ? 'text-danger' : tool.permission === 'confirm' ? 'text-warning' : ''
        }`}
      >
        {PERMISSION_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
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
  const [catalog, setCatalog] = useState<ToolCatalog | null>(null)
  const [toolsLoading, setToolsLoading] = useState(true)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [toolLog, setToolLog] = useState<ToolLogEntry[]>([])
  const [savingTool, setSavingTool] = useState<string | null>(null)
  /** Adapter id being applied (or `'__reset__'`), `null` when idle. */
  const [switching, setSwitching] = useState<string | null>(null)
  /** Failure of the last adapter switch — shown next to the adapter list. */
  const [switchError, setSwitchError] = useState<string | null>(null)
  /** Unsaved model edits, keyed by the adapter they belong to. */
  const [modelDraft, setModelDraft] = useState<{ provider: string; value: string } | null>(null)
  const [caps, setCaps] = useState<CapabilityReport | null>(null)
  const [capsLoading, setCapsLoading] = useState(true)
  const [capsError, setCapsError] = useState<string | null>(null)
  /** Capability id whose action is in flight, `null` when idle. */
  const [capBusy, setCapBusy] = useState<string | null>(null)
  /** Unsaved calendar-connect form. */
  const [calForm, setCalForm] = useState<{
    source: CalendarSource['kind']
    target: string
    label: string
  }>({ source: 'local_ics', target: '', label: '' })
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

  const loadTools = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextCatalog, nextLog] = await Promise.all([
        getToolCatalog(signal),
        getToolLog(12, signal),
      ])
      setCatalog(nextCatalog)
      setToolLog(nextLog.entries)
      setToolsError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setToolsError(messageOf(caught))
    } finally {
      setToolsLoading(false)
    }
  }, [])

  const changePermission = useCallback(
    async (name: string, level: PermissionLevel | null) => {
      setSavingTool(name)
      try {
        await setPermission(name, level)
        await loadTools()
        pulse('success', 1000)
      } catch (caught) {
        setToolsError(messageOf(caught))
        pulse('error', 1500)
      } finally {
        setSavingTool(null)
      }
    },
    [loadTools, pulse],
  )

  const resetPermissions = useCallback(async () => {
    setSavingTool('__all__')
    try {
      await clearPermissions()
      await loadTools()
      pulse('success', 1000)
    } catch (caught) {
      setToolsError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setSavingTool(null)
    }
  }, [loadTools, pulse])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void loadTools(controller.signal)
    return () => controller.abort()
  }, [loadTools])

  const loadCaps = useCallback(async (signal?: AbortSignal) => {
    try {
      setCaps(await getCapabilities(signal))
      setCapsError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setCapsError(messageOf(caught))
    } finally {
      setCapsLoading(false)
    }
  }, [])

  /** Run one capability action; the reply is the rebuilt report. */
  const runCap = useCallback(
    async (id: string, body: CapabilityActionBody): Promise<boolean> => {
      setCapBusy(id)
      try {
        setCaps(await capabilityAction(id, body))
        setCapsError(null)
        pulse('success', 1000)
        return true
      } catch (caught) {
        setCapsError(messageOf(caught))
        pulse('error', 1500)
        return false
      } finally {
        setCapBusy(null)
      }
    },
    [pulse],
  )

  const connectCalendar = async () => {
    if (capBusy !== null) return
    const ok = await runCap('calendar', {
      action: 'connect',
      source: calForm.source,
      target: calForm.target.trim() || undefined,
      label: calForm.label.trim() || undefined,
    })
    if (ok) setCalForm((form) => ({ ...form, target: '', label: '' }))
  }

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void loadCaps(controller.signal)
    return () => controller.abort()
  }, [loadCaps])

  const calendarInfo = caps?.capabilities.find((cap) => cap.id === 'calendar') ?? null

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
      <section>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">AI provider</h2>
            <p className="text-xs text-muted">
              Tap an adapter under <span className="text-ink">Installed provider adapters</span> to
              switch — it applies immediately and survives a restart. Defaults come from{' '}
              <code className="font-mono text-muted">LUXION_LLM__*</code> in{' '}
              <code className="font-mono text-muted">.env</code>.
            </p>
          </div>
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
        </div>

        {error ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
      </section>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
      </section>

      <section>
        <div className="flex flex-wrap items-start justify-between gap-3">
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
      </section>

      <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">Context &amp; usage</h3>
            <p className="mt-1.5 text-xs text-muted">
              How much of the window each turn sends, plus lifetime token spend. Budgets come from{' '}
              <code className="font-mono text-muted">LUXION_CONTEXT__*</code> in{' '}
              <code className="font-mono text-muted">.env</code>.
            </p>
          </div>
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
        </div>

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
      </section>

      <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <TerminalIcon className="size-4 text-tint" />
            <h3 className="text-sm font-semibold text-ink">Tools</h3>
            {catalog ? (
              <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
                autonomy {catalog.autonomy_level} · {catalog.tools.length} registered
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void loadTools()}
            disabled={toolsLoading || savingTool !== null}
            className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
              toolsLoading || savingTool !== null
                ? 'cursor-wait text-muted'
                : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
            }`}
          >
            <RefreshIcon className={`size-3.5 ${toolsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        <p className="mt-1.5 text-xs text-muted">
          What the model may run on your machine (PRD §18–21). The decision is the stricter of the
          autonomy level, the high-risk guardrail and your override below. Policy comes from{' '}
          <code className="font-mono text-muted">LUXION_TOOLS__*</code> in{' '}
          <code className="font-mono text-muted">.env</code>.
        </p>

        {toolsError ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{toolsError}</span>
          </div>
        ) : null}

        {catalog && !catalog.enabled ? (
          <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-xs text-warning">
            Tool execution is disabled — the model is never offered any tools.
          </div>
        ) : null}

        {toolsLoading && !catalog ? (
          <p className="mt-4 text-xs text-muted">Loading tool catalog…</p>
        ) : null}

        {catalog ? (
          <>
            <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
              {catalog.tools.map((tool) => (
                <ToolRow
                  key={tool.name}
                  tool={tool}
                  busy={savingTool !== null}
                  onChange={(name, level) => void changePermission(name, level)}
                />
              ))}
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="font-mono text-[11px] text-muted/70">
                {catalog.defaults
                  .map((entry) => `${entry.risk} → ${entry.level}`)
                  .join(' · ')}
              </p>
              <button
                type="button"
                onClick={() => void resetPermissions()}
                disabled={savingTool !== null}
                className="cursor-pointer rounded-lg border border-white/15 px-3 py-1.5 text-xs text-muted transition duration-200 hover:border-danger/50 hover:text-danger disabled:cursor-wait disabled:opacity-60"
              >
                Reset all overrides
              </button>
            </div>

            <div className="mt-5 rounded-xl border border-white/10 bg-surface/60 p-4">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xs uppercase tracking-wider text-muted">Recent tool activity</h4>
                <span className="font-mono text-[10px] text-muted/60">audit log · newest first</span>
              </div>
              {toolLog.length ? (
                <ul className="mt-3 flex flex-col gap-1.5 text-[11px]">
                  {toolLog.map((entry, index) => (
                    <li
                      key={`${entry.timestamp}-${index}`}
                      className="flex items-center justify-between gap-3"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="font-mono text-ink">{entry.tool}</span>
                        {entry.target ? (
                          <span className="truncate font-mono text-muted/70" title={entry.target}>
                            {entry.target}
                          </span>
                        ) : null}
                      </span>
                      <span className="flex shrink-0 items-center gap-2 font-mono">
                        <span className={RESULT_CLASS[entry.result]}>{entry.result}</span>
                        <span className="text-muted/70">
                          {entry.duration_ms != null ? `${Math.round(entry.duration_ms)}ms` : '—'}
                        </span>
                        <span className="text-muted/60">
                          {new Date(entry.timestamp).toLocaleTimeString()}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-[11px] text-muted/70">No tool has run yet.</p>
              )}
            </div>
          </>
        ) : null}
      </section>

      <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldIcon className="size-4 text-tint" />
            <h3 className="text-sm font-semibold text-ink">Permissions &amp; capabilities</h3>
            {caps ? (
              <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
                {caps.capabilities.length} capabilities
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void loadCaps()}
            disabled={capsLoading || capBusy !== null}
            className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
              capsLoading || capBusy !== null
                ? 'cursor-wait text-muted'
                : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
            }`}
          >
            <RefreshIcon className={`size-3.5 ${capsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        <p className="mt-1.5 text-xs text-muted">
          The hard gate that runs <em>before</em> tool permissions (PRD §39): when a capability is
          off, the tool is denied no matter how high the autonomy level is. Windows privacy
          switches open in Settings; in-app consents are stored in{' '}
          <code className="font-mono text-muted">capabilities.json</code>.
        </p>

        {capsError ? (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{capsError}</span>
          </div>
        ) : null}

        {capsLoading && !caps ? (
          <p className="mt-4 text-xs text-muted">Loading capabilities…</p>
        ) : null}

        {caps ? (
          <>
            <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
              {caps.capabilities.map((cap) => (
                <div
                  key={cap.id}
                  className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-white/8 py-2.5 last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-ink">{cap.label}</span>
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${STATE_CLASS[cap.state]}`}
                      >
                        {STATE_LABEL[cap.state]}
                      </span>
                      <span className="rounded border border-white/12 px-1.5 py-0.5 font-mono text-[10px] text-muted/70 uppercase">
                        {cap.kind === 'os' ? 'windows' : cap.kind}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted">
                      {cap.description}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-muted/60">{cap.reason}</p>
                    {cap.id === 'calendar' && cap.sources.length ? (
                      <ul className="mt-1.5 flex flex-col gap-1">
                        {cap.sources.map((source) => (
                          <li
                            key={source.id}
                            className="flex items-center gap-2 font-mono text-[10px] text-muted/70"
                          >
                            <span
                              className={
                                source.writable
                                  ? 'text-status-ok'
                                  : 'border border-white/15 px-1 py-0.5 uppercase'
                              }
                            >
                              {source.kind === 'local_ics' ? 'local' : 'feed'}
                            </span>
                            <span className="truncate" title={source.target}>
                              {source.label} · {source.target}
                            </span>
                            <button
                              type="button"
                              disabled={capBusy !== null}
                              onClick={() =>
                                void runCap('calendar', { action: 'disconnect', id: source.id })
                              }
                              className="ml-auto shrink-0 cursor-pointer text-danger/80 transition duration-200 hover:text-danger disabled:cursor-wait disabled:opacity-60"
                            >
                              Remove
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {cap.actions.includes('open_settings') ? (
                      <button
                        type="button"
                        onClick={() => void runCap(cap.id, { action: 'open_settings' })}
                        disabled={capBusy !== null}
                        className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs text-muted transition duration-200 hover:border-tint/60 hover:text-ink disabled:cursor-wait disabled:opacity-60"
                      >
                        Windows settings
                      </button>
                    ) : null}
                    {cap.actions.includes('deny') ? (
                      <button
                        type="button"
                        onClick={() =>
                          void runCap(cap.id, {
                            action: cap.state === 'granted' ? 'deny' : 'grant',
                          })
                        }
                        disabled={capBusy !== null}
                        className={`rounded-lg border px-2.5 py-1.5 text-xs transition duration-200 disabled:cursor-wait disabled:opacity-60 ${
                          cap.state === 'granted'
                            ? 'border-danger/40 text-danger hover:bg-danger/10'
                            : 'border-status-ok/40 text-status-ok hover:bg-status-ok/10'
                        }`}
                      >
                        {capBusy === cap.id
                          ? 'Saving…'
                          : cap.state === 'granted'
                            ? 'Turn off'
                            : 'Allow'}
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 p-4">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xs uppercase tracking-wider text-muted">Calendar sources</h4>
                {calendarInfo && calendarInfo.sources.length ? (
                  <button
                    type="button"
                    disabled={capBusy !== null}
                    onClick={() => void runCap('calendar', { action: 'disconnect' })}
                    className="cursor-pointer rounded-lg border border-white/15 px-2.5 py-1 text-[11px] text-muted transition duration-200 hover:border-danger/50 hover:text-danger disabled:cursor-wait disabled:opacity-60"
                  >
                    Disconnect all
                  </button>
                ) : null}
              </div>
              <p className="mt-1 text-[11px] text-muted/70">
                A local <code className="font-mono">.ics</code> file Luxion can write to, or a
                read-only secret iCal address from Google, Apple or Outlook.
              </p>
              <div className="mt-3 flex flex-wrap items-end gap-2">
                <label className="flex flex-col gap-1 text-[10px] tracking-[0.16em] text-muted uppercase">
                  Source
                  <select
                    value={calForm.source}
                    disabled={capBusy !== null}
                    onChange={(event) =>
                      setCalForm({
                        ...calForm,
                        source: event.target.value as CalendarSource['kind'],
                      })
                    }
                    className="h-8 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                  >
                    <option value="local_ics">Local .ics file</option>
                    <option value="ics_subscription">Subscribe (iCal URL)</option>
                  </select>
                </label>
                <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-[10px] tracking-[0.16em] text-muted uppercase">
                  {calForm.source === 'local_ics' ? 'File path (blank = default)' : 'iCal URL'}
                  <input
                    value={calForm.target}
                    disabled={capBusy !== null}
                    onChange={(event) => setCalForm({ ...calForm, target: event.target.value })}
                    placeholder={
                      calForm.source === 'local_ics'
                        ? 'Documents/Luxion/calendar.ics'
                        : 'https://calendar.google.com/calendar/ical/…/basic.ics'
                    }
                    className="h-8 rounded-lg border border-white/15 bg-surface/70 px-2.5 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                  />
                </label>
                <label className="flex flex-col gap-1 text-[10px] tracking-[0.16em] text-muted uppercase">
                  Label
                  <input
                    value={calForm.label}
                    disabled={capBusy !== null}
                    onChange={(event) => setCalForm({ ...calForm, label: event.target.value })}
                    placeholder="Work"
                    className="h-8 w-32 rounded-lg border border-white/15 bg-surface/70 px-2.5 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void connectCalendar()}
                  disabled={
                    capBusy !== null ||
                    (calForm.source === 'ics_subscription' && !calForm.target.trim())
                  }
                  className={`h-8 shrink-0 rounded-lg border px-3 text-xs transition duration-200 ${
                    capBusy !== null ||
                    (calForm.source === 'ics_subscription' && !calForm.target.trim())
                      ? 'cursor-default border-white/10 text-muted/50'
                      : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
                  }`}
                >
                  {capBusy === 'calendar' ? 'Connecting…' : 'Connect'}
                </button>
              </div>
            </div>
          </>
        ) : null}
      </section>

      <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
        <div className="flex items-center gap-2">
          <TypeIcon className="size-4 text-tint" />
          <h3 className="text-sm font-semibold text-ink">Appearance</h3>
        </div>
        <p className="mt-1.5 text-xs text-muted">
          Fonts, type scale and accent colour for the whole interface. Stored in this browser and
          applied immediately.
        </p>

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
      </section>

      <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <GaugeIcon className="size-4 text-tint" />
            <h3 className="text-sm font-semibold text-ink">Graphics</h3>
          </div>
          <span className="font-mono text-[11px] text-muted/70">
            {profile.particles} particles · {profile.rings} rings · DPR{' '}
            {profile.dpr[0]}–{profile.dpr[1]}
          </span>
        </div>
        <p className="mt-1.5 text-xs text-muted">
          Rendering preset for the 3D core. Saved in this browser, applied immediately.
        </p>

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
      </section>
    </div>
  )
}
