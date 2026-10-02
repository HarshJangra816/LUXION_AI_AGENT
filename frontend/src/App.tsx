import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { AmbientBackground } from './components/AmbientBackground'
import { AIStatus } from './components/AIStatus'
import { Logo } from './components/Logo'
import { RefreshIcon } from './components/icons'
import { StatusDot } from './components/StatusDot'
import { ChatPage } from './features/chat/ChatPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { SettingsPage } from './features/settings/SettingsPage'
import { fetchHealth, statusLabel, type BackendState } from './lib/api'
import { useAIState } from './lib/aiState'

// three.js is the single biggest dependency — keep it out of the first paint.
const AI3DCore = lazy(() => import('./components/three/AI3DCore'))

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', ready: true },
  { id: 'chat', label: 'Chat', ready: true },
  { id: 'memory', label: 'Memory', ready: false, phase: 'Phase 5' },
  { id: 'settings', label: 'Settings', ready: true },
] as const

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  dashboard: { title: 'Dashboard', subtitle: 'System health and quick actions' },
  chat: { title: 'Chat', subtitle: 'Phase 1 - streaming conversation' },
  settings: { title: 'Settings', subtitle: 'Phase 1 - AI provider and graphics' },
}

function BrandMark() {
  return (
    <div className="flex items-center gap-2.5">
      <Logo size={32} glow />
      <div>
        <div className="text-sm font-semibold tracking-wide text-ink">Luxion</div>
        <div className="text-[11px] text-muted">Personal AI Agent</div>
      </div>
    </div>
  )
}

function Shell() {
  const [state, setState] = useState<BackendState>({ kind: 'connecting' })
  const [activeNav, setActiveNav] = useState<string>('dashboard')
  const [pendingDraft, setPendingDraft] = useState('')
  const timerRef = useRef<number | undefined>(undefined)

  const { state: aiState, setState: setAIState, pulse } = useAIState()
  const aiStateRef = useRef(aiState)
  const prevKindRef = useRef<BackendState['kind']>(state.kind)

  useEffect(() => {
    aiStateRef.current = aiState
  }, [aiState])

  const probe = useCallback(async (signal?: AbortSignal): Promise<boolean> => {
    try {
      const health = await fetchHealth(signal)
      setState({ kind: 'online', health })
      return true
    } catch (error) {
      if (signal?.aborted) return false
      setState({ kind: 'offline', error: error instanceof Error ? error.message : String(error) })
      return false
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async probe, no sync setState
    void probe(controller.signal)
    timerRef.current = window.setInterval(() => {
      void probe(controller.signal)
    }, 5000)
    return () => {
      controller.abort()
      window.clearInterval(timerRef.current)
    }
  }, [probe])

  // Backend reachability is a real state of the system — surface it on the core.
  useEffect(() => {
    if (prevKindRef.current === state.kind) return
    prevKindRef.current = state.kind
    if (state.kind === 'offline') setAIState('warning')
    else if (state.kind === 'online' && aiStateRef.current === 'warning') setAIState('idle')
  }, [state.kind, setAIState])

  const navigate = useCallback((id: string) => {
    setActiveNav(id)
    if (id !== 'chat') setPendingDraft('')
  }, [])

  const askLuxion = useCallback((text: string) => {
    setPendingDraft(text)
    setActiveNav('chat')
  }, [])

  const meta = PAGE_META[activeNav] ?? PAGE_META.dashboard

  return (
    <div className="relative flex h-full">
      <AmbientBackground />
      <Suspense fallback={null}>
        <AI3DCore showHud={activeNav === 'dashboard'} />
      </Suspense>
      {/* readability scrim: dims the glow before it reaches any content */}
      <div aria-hidden className="scrim pointer-events-none fixed inset-0 z-[5]" />

      <aside className="relative z-10 hidden w-60 shrink-0 flex-col border-r border-white/1 bg-panel/10 backdrop-blur-xl md:flex">
        <div className="px-5 py-5">
          <BrandMark />
        </div>

        <nav className="flex flex-col gap-1 px-3 py-2">
          {NAV_ITEMS.map((item) => {
            const active = activeNav === item.id && item.ready
            return (
              <button
                key={item.id}
                type="button"
                disabled={!item.ready}
                onClick={() => item.ready && navigate(item.id)}
                className={`flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm transition duration-200 ${
                  active
                    ? 'bg-tint/12 text-ink ring-1 ring-inset ring-tint/45'
                    : item.ready
                      ? 'text-muted hover:bg-panel-2 hover:text-ink'
                      : 'cursor-not-allowed text-muted/50'
                }`}
              >
                <span>{item.label}</span>
                {'phase' in item && item.phase ? (
                  <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-muted/70">
                    {item.phase}
                  </span>
                ) : null}
              </button>
            )
          })}
        </nav>

        <div className="mt-auto space-y-3 border-t border-white/10 px-5 py-4">
          <AIStatus />
          <div className="flex items-center gap-2 text-xs text-muted">
            <StatusDot state={state} />
            <span className="truncate">{statusLabel(state)}</span>
          </div>
        </div>
      </aside>

      <main className="relative z-10 flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-white/10 bg-surface/20 px-6 py-4 backdrop-blur-xl md:px-8">
          <div className="flex items-center gap-3">
            <div className="md:hidden">
              <BrandMark />
            </div>
            <div className="hidden md:block">
              <h1 className="text-lg font-semibold text-ink">{meta.title}</h1>
              <p className="text-xs text-muted">{meta.subtitle}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 md:hidden">
              <AIStatus compact />
            </div>
            <div className="hidden items-center gap-2 text-xs text-muted md:flex">
              <StatusDot state={state} />
              <span className="font-mono text-[11px]">{statusLabel(state)}</span>
            </div>
            <button
              type="button"
              onClick={() => {
                void probe().then((ok) => pulse(ok ? 'success' : 'warning', 1400))
              }}
              className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-white/15 bg-panel-2/60 px-3 py-1.5 text-xs text-muted transition duration-200 hover:border-tint/60 hover:text-ink"
            >
              <RefreshIcon className="size-3.5" />
              Refresh
            </button>
          </div>
        </header>

        {/* mobile navigation */}
        <nav className="relative z-10 flex gap-1.5 overflow-x-auto border-b border-white/10 bg-surface/75 px-4 py-2 backdrop-blur-xl md:hidden">
          {NAV_ITEMS.map((item) => {
            const active = activeNav === item.id && item.ready
            return (
              <button
                key={item.id}
                type="button"
                disabled={!item.ready}
                onClick={() => item.ready && navigate(item.id)}
                className={`shrink-0 rounded-full px-3 py-1.5 font-mono text-[11px] tracking-wide transition duration-200 ${
                  active
                    ? 'bg-tint/15 text-ink'
                    : item.ready
                      ? 'text-muted hover:bg-panel-2 hover:text-ink'
                      : 'cursor-not-allowed text-muted/40'
                }`}
              >
                {item.label}
              </button>
            )
          })}
        </nav>

        {activeNav === 'chat' ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <ChatPage initialDraft={pendingDraft} />
          </div>
        ) : activeNav === 'settings' ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <SettingsPage />
          </div>
        ) : (
          <DashboardPage
            state={state}
            onRefresh={() => void probe()}
            onOpenChat={() => navigate('chat')}
            onAsk={askLuxion}
          />
        )}
      </main>
    </div>
  )
}

export default function App() {
  return <Shell />
}
