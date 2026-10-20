import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, RefreshIcon, ShieldIcon, TerminalIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { ApiError } from '../../lib/api'
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
import { useAIState } from '../../lib/aiState'

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
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

/** The tool framework's two pages of controls: policy (Tools) + hard gates (Permissions). */
export function ToolsPage() {
  const [catalog, setCatalog] = useState<ToolCatalog | null>(null)
  const [toolsLoading, setToolsLoading] = useState(true)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [toolLog, setToolLog] = useState<ToolLogEntry[]>([])
  const [savingTool, setSavingTool] = useState<string | null>(null)
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

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6 md:p-8">
      <SettingsCard
        id="tools"
        title="Tools"
        icon={<TerminalIcon className="size-4 text-tint" />}
        defaultOpen
        badge={
          catalog ? (
            <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
              autonomy {catalog.autonomy_level} · {catalog.tools.length} registered
            </span>
          ) : null
        }
        hint={
          <>
            What the model may run on your machine (PRD §18–21). The decision is the stricter of
            the autonomy level, the high-risk guardrail and your override below. Policy comes from{' '}
            <code className="font-mono text-muted">LUXION_TOOLS__*</code> in{' '}
            <code className="font-mono text-muted">.env</code>.
          </>
        }
        actions={
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
        }
      >
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
      </SettingsCard>

      <SettingsCard
        id="permissions"
        title="Permissions & capabilities"
        icon={<ShieldIcon className="size-4 text-tint" />}
        badge={
          caps ? (
            <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
              {caps.capabilities.length} capabilities
            </span>
          ) : null
        }
        hint={
          <>
            The hard gate that runs <em>before</em> tool permissions (PRD §39): when a capability
            is off, the tool is denied no matter how high the autonomy level is. Windows privacy
            switches open in Settings; in-app consents are stored in{' '}
            <code className="font-mono text-muted">capabilities.json</code>.
          </>
        }
        actions={
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
        }
      >
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
      </SettingsCard>
    </div>
  )
}
