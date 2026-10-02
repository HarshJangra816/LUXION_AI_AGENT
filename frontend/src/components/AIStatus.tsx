import { AI_STATE_LABEL, useAIState, type AIState } from '../lib/aiState'

const TONE: Record<AIState, string> = {
  idle: 'border-white/15 text-muted',
  listening: 'border-tint/45 text-tint',
  thinking: 'border-tint/45 text-tint',
  processing: 'border-tint/55 text-tint',
  working: 'border-tint/55 text-tint',
  speaking: 'border-tint/55 text-tint',
  success: 'border-status-ok/50 text-status-ok',
  warning: 'border-warning/50 text-warning',
  error: 'border-danger/60 text-danger',
}

const DOT: Record<AIState, string> = {
  idle: 'bg-muted',
  listening: 'bg-tint animate-pulse',
  thinking: 'bg-tint animate-pulse',
  processing: 'bg-tint animate-pulse',
  working: 'bg-tint animate-pulse',
  speaking: 'bg-tint animate-pulse',
  success: 'bg-status-ok',
  warning: 'bg-warning animate-pulse',
  error: 'bg-danger animate-pulse',
}

/** Compact state chip — sidebar footer and chat header. */
export function AIStatus({ compact = false }: { compact?: boolean }) {
  const { state } = useAIState()
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border bg-surface/60 font-mono tracking-[0.16em] uppercase backdrop-blur-md ${
        compact ? 'px-2 py-1 text-[9px]' : 'px-2.5 py-1 text-[10px]'
      } ${TONE[state]}`}
    >
      <span className={`size-1.5 rounded-full ${DOT[state]}`} />
      {AI_STATE_LABEL[state]}
    </span>
  )
}
