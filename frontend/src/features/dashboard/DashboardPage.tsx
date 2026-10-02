import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ArrowIcon, ChatIcon, RefreshIcon } from '../../components/icons'
import { GlassPanel } from '../../components/GlassPanel'
import { Logo } from '../../components/Logo'
import { StatusDot } from '../../components/StatusDot'
import { statusLabel, type BackendState } from '../../lib/api'

const USER_NAME = 'Harsh'

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  if (minutes < 60) return `${minutes}m ${rest}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 5) return 'Good night'
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-panel/75 p-4 backdrop-blur-xl transition duration-200 hover:-translate-y-0.5 hover:border-tint/45">
      <div className="text-[10px] tracking-[0.18em] text-muted uppercase">{label}</div>
      <div className="mt-2 truncate font-mono text-lg text-ink" title={value}>
        {value}
      </div>
      <div className="mt-1 truncate text-xs text-muted/80" title={hint}>
        {hint ?? ' '}
      </div>
    </div>
  )
}

function Chip({ tone, children }: { tone: 'ok' | 'warn' | 'idle'; children: ReactNode }) {
  const dot =
    tone === 'ok' ? 'bg-status-ok' : tone === 'warn' ? 'bg-warning' : 'bg-tint'
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-panel/75 px-3 py-1.5 font-mono text-[10px] tracking-[0.16em] text-muted uppercase backdrop-blur-xl">
      <span className={`size-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  )
}

function apiStatusText(state: BackendState): string {
  if (state.kind === 'online') return `GET /api/health → 200 · ${state.health.status}`
  if (state.kind === 'offline') return `GET /api/health → ${state.error}`
  return 'GET /api/health → connecting…'
}

/** Scroll distance (px) over which the core HUD recedes, and over which the
 *  pinned hero vanishes once it has reached the top. */
const HUD_FADE_DISTANCE = 160

export function DashboardPage({
  state,
  onRefresh,
  onOpenChat,
  onAsk,
}: {
  state: BackendState
  onRefresh: () => void
  onOpenChat: () => void
  onAsk: (text: string) => void
}) {
  const health = state.kind === 'online' ? state.health : null
  const [question, setQuestion] = useState('')
  const scrollerRef = useRef<HTMLDivElement>(null)
  const frameRef = useRef(0)

  /*
   * Publish scroll progress as a CSS variable instead of React state: the HUD
   * recedes purely in CSS (transform + opacity) with no re-render of the
   * shell on every scroll tick.
   */
  function publishScroll() {
    if (frameRef.current) return
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0
      const el = scrollerRef.current
      if (!el) return
      const progress = Math.min(1, Math.max(0, el.scrollTop / HUD_FADE_DISTANCE))
      document.documentElement.style.setProperty('--lux-core-scroll', progress.toFixed(4))
    })
  }

  useEffect(() => {
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
      document.documentElement.style.setProperty('--lux-core-scroll', '0')
    }
  }, [])

  function submit(event: FormEvent) {
    event.preventDefault()
    const text = question.trim()
    if (!text) {
      onOpenChat()
      return
    }
    onAsk(text)
    setQuestion('')
  }

  return (
    <div
      ref={scrollerRef}
      onScroll={publishScroll}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      {/*
        Core band: strip reserved for the WebGL core and the telemetry HUD
        (SYS / RENDER / MODE / CHARGE) that AI3DCore draws at fixed viewport
        coordinates. The HUD recedes through --lux-core-scroll as soon as the
        content below starts rising into this strip.
      */}
      <div className="h-[46vh] min-h-[280px]" aria-hidden />

      <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 px-6 pt-3 pb-12">
        <div className="flex items-center gap-3">
          <Logo size={36} glow />
          <span className="font-mono text-[11px] tracking-[0.5em] text-tint">LUXION</span>
        </div>

        <div className="text-center">
          <h2 className="text-2xl font-semibold text-ink md:text-3xl">
            {greeting()}, {USER_NAME}.
          </h2>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted">
            Your private AI agent is running locally. Ask anything — replies stream in as the
            model generates them.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="flex w-full items-center gap-2 rounded-2xl border border-white/12 bg-panel/75 p-2 shadow-[0_18px_50px_-24px_rgba(0,0,0,0.9)] backdrop-blur-xl transition duration-200 focus-within:border-tint/70"
        >
          <span className="pl-3 font-mono text-xs text-tint">›</span>
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask Luxion a question…"
            aria-label="Ask Luxion a question"
            className="min-w-0 flex-1 bg-transparent px-1 py-2 text-sm text-ink placeholder:text-muted/70 focus:outline-none"
          />
          <button
            type="submit"
            className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition duration-200 hover:-translate-y-0.5 hover:brightness-110"
          >
            Ask
            <ArrowIcon className="size-4" />
          </button>
        </form>

        <div className="flex flex-wrap items-center justify-center gap-2">
          <Chip tone={state.kind === 'online' ? 'ok' : state.kind === 'offline' ? 'warn' : 'idle'}>
            backend · {state.kind}
          </Chip>
          <Chip tone="idle">phase 1 · chat ready</Chip>
          <Chip tone="idle">memory · phase 5</Chip>
        </div>

        <section className="grid w-full grid-cols-2 gap-3 xl:grid-cols-4">
          <Metric
            label="Backend"
            value={state.kind === 'online' ? 'online' : state.kind}
            hint={
              state.kind === 'offline'
                ? state.error
                : health
                  ? health.service
                  : 'waiting for /api/health'
            }
          />
          <Metric
            label="Database"
            value={health ? health.database : '—'}
            hint={health ? 'sqlite (phase 0)' : 'not reported yet'}
          />
          <Metric
            label="Version"
            value={health ? `${health.version}` : '—'}
            hint={health ? `api v${health.api_version}` : 'not reported yet'}
          />
          <Metric
            label="Uptime"
            value={health ? formatUptime(health.uptime_s) : '—'}
            hint={health ? new Date(health.time_utc).toLocaleTimeString() : 'not reported yet'}
          />
        </section>

        <GlassPanel label="phase 1 · chat" className="w-full">
          <div className="p-5">
            <div className="flex items-center gap-2 text-sm font-medium text-ink">
              <ChatIcon className="size-4 text-tint" />
              Conversations, streaming replies and the LLM provider abstraction are live
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              Pick a provider in Settings, then open Chat and send your first message. Tokens
              arrive over SSE as the model generates them — no polling, no fake typing.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={onOpenChat}
                className="cursor-pointer rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition duration-200 hover:-translate-y-0.5 hover:brightness-110"
              >
                Open chat
              </button>
              <button
                type="button"
                onClick={onRefresh}
                className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs text-muted transition duration-200 hover:border-tint/60 hover:text-ink"
              >
                <RefreshIcon className="size-3.5" />
                Refresh health
              </button>
              <div className="ml-auto hidden items-center gap-2 text-xs text-muted sm:flex">
                <StatusDot state={state} />
                <span>{statusLabel(state)}</span>
              </div>
            </div>
            <div className="mt-4 border-t border-white/10 pt-4 font-mono text-[11px] text-muted/70">
              {apiStatusText(state)}
            </div>
          </div>
        </GlassPanel>

        <p className="font-mono text-[11px] tracking-[0.2em] text-muted/50 uppercase">
          phases 2–13 queued
        </p>
      </div>
    </div>
  )
}
