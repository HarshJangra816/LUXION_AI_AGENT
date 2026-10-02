import { useState } from 'react'
import { CheckIcon, ShieldIcon, TerminalIcon, XIcon } from '../../components/icons'
import { Logo } from '../../components/Logo'
import type { ChatConfirm, ToolSummary } from '../../lib/chat'

/** Terminal statuses come from the backend; `start` only exists live. */
export type ToolRunStatus = ToolSummary['status'] | 'start'

export interface ToolRunView extends Omit<ToolSummary, 'status'> {
  status: ToolRunStatus
  /** Provider call id — lets a terminal event replace its own `start` chip. */
  id?: string
}

export interface ChatItem {
  key: string
  role: 'user' | 'assistant'
  content: string
  createdAt?: string | null
  streaming?: boolean
  /** Tool runs for this turn, in the order they were started. */
  tools?: ToolRunView[]
  /** A confirmation the model is waiting on (cleared once answered). */
  confirm?: ChatConfirm | null
}

const STATUS_COPY: Record<ToolRunStatus, { label: string; className: string }> = {
  start: { label: 'running', className: 'border-tint/50 bg-tint/10 text-tint' },
  ok: { label: 'ok', className: 'border-status-ok/40 bg-status-ok/10 text-status-ok' },
  error: { label: 'failed', className: 'border-danger/40 bg-danger/10 text-danger' },
  denied: { label: 'denied', className: 'border-danger/40 bg-danger/10 text-danger' },
  timeout: { label: 'timed out', className: 'border-warning/40 bg-warning/10 text-warning' },
  invalid_args: {
    label: 'bad args',
    className: 'border-warning/40 bg-warning/10 text-warning',
  },
}

/** Tool chips shown above the reply text (running → terminal state). */
function ToolRunList({ tools }: { tools: ToolRunView[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="mb-2.5 flex flex-col gap-1.5">
      {tools.map((tool, index) => {
        const copy = STATUS_COPY[tool.status]
        const key = `${tool.name}-${index}`
        return (
          <div key={key} className="flex flex-col gap-1">
            <button
              type="button"
              onClick={() => setExpanded(expanded === key ? null : key)}
              className={`flex w-fit max-w-full cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left font-mono text-[11px] transition duration-200 hover:border-white/30 ${copy.className}`}
            >
              <TerminalIcon className="size-3.5 shrink-0" />
              <span className="truncate">{tool.name}</span>
              <span className="shrink-0 uppercase tracking-wider opacity-80">{copy.label}</span>
              {tool.status !== 'start' && tool.duration_ms != null ? (
                <span className="shrink-0 opacity-70">{Math.round(tool.duration_ms)}ms</span>
              ) : null}
            </button>

            {expanded === key ? (
              <div className="rounded-lg border border-white/10 bg-surface/70 p-2.5 font-mono text-[11px] text-muted">
                <div className="text-[10px] uppercase tracking-wider text-muted/60">arguments</div>
                <div className="mt-0.5 break-all text-ink/80">
                  {Object.keys(tool.args).length ? JSON.stringify(tool.args) : '(none)'}
                </div>
                {tool.output ? (
                  <>
                    <div className="mt-2 text-[10px] uppercase tracking-wider text-muted/60">
                      output
                    </div>
                    <div className="mt-0.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-all text-ink/80">
                      {tool.output}
                    </div>
                  </>
                ) : null}
                {tool.error ? <div className="mt-2 break-all text-danger">{tool.error}</div> : null}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

/** Allow/Deny card for a `confirm`-level tool (PRD §21). */
function ConfirmCard({
  confirm,
  answering,
  error,
  onAnswer,
}: {
  confirm: ChatConfirm
  answering: boolean
  error: string | null
  onAnswer: (id: string, approved: boolean) => void
}) {
  return (
    <div className="mb-2.5 rounded-xl border border-warning/40 bg-warning/10 p-3">
      <div className="flex items-start gap-2">
        <ShieldIcon className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink">
            <span className="font-mono">{confirm.name}</span>
            <span className="rounded border border-warning/50 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-warning uppercase">
              {confirm.risk} risk
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {confirm.reason || 'Luxion wants to run this tool.'}
          </p>
          <pre className="mt-2 max-h-24 overflow-y-auto rounded border border-white/10 bg-surface/70 p-2 font-mono text-[11px] break-all whitespace-pre-wrap text-ink/80">
            {JSON.stringify(confirm.args, null, 1)}
          </pre>
          {error ? <p className="mt-2 text-[11px] text-danger">{error}</p> : null}
          <div className="mt-2.5 flex gap-2">
            <button
              type="button"
              disabled={answering}
              onClick={() => onAnswer(confirm.id, true)}
              className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent transition duration-200 hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
            >
              <CheckIcon className="size-3.5" />
              Allow
            </button>
            <button
              type="button"
              disabled={answering}
              onClick={() => onAnswer(confirm.id, false)}
              className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-muted transition duration-200 hover:border-danger/50 hover:text-danger disabled:cursor-wait disabled:opacity-60"
            >
              <XIcon className="size-3.5" />
              Deny
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Splits fenced code blocks out of plain text (no Markdown dependency). */
function Body({ text }: { text: string }) {
  const segments = text.split('```')
  return (
    <>
      {segments.map((segment, index) => {
        if (index % 2 === 0) return <span key={index}>{segment}</span>
        const newline = segment.indexOf('\n')
        const language = newline === -1 ? '' : segment.slice(0, newline).trim()
        const code = (newline === -1 ? segment : segment.slice(newline + 1)).replace(/\n$/, '')
        return (
          <pre
            key={index}
            className="my-2 overflow-x-auto rounded-lg border border-white/10 bg-surface/80 p-3 font-mono text-xs text-ink/90"
          >
            {language ? (
              <div className="mb-1.5 text-[10px] uppercase tracking-wider text-muted/70">
                {language}
              </div>
            ) : null}
            <code>{code}</code>
          </pre>
        )
      })}
    </>
  )
}

export function MessageBubble({
  item,
  onAnswer,
  answering,
  answerError,
}: {
  item: ChatItem
  onAnswer?: (id: string, approved: boolean) => void
  answering?: boolean
  answerError?: string | null
}) {
  const isUser = item.role === 'user'
  const hasActivity = Boolean(item.tools?.length) || Boolean(item.confirm)

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {!isUser ? (
        <div className="mt-1 flex size-7 shrink-0 items-center justify-center">
          <Logo size={28} />
        </div>
      ) : null}

      <div className={`flex max-w-[min(46rem,85%)] flex-col ${isUser ? 'items-end' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? 'rounded-br-md border border-tint/30 bg-tint/12 text-ink'
              : 'rounded-bl-md border border-white/10 bg-panel/85 text-ink backdrop-blur-xl'
          }`}
        >
          {!isUser && item.tools?.length ? <ToolRunList tools={item.tools} /> : null}
          {!isUser && item.confirm && onAnswer ? (
            <ConfirmCard
              confirm={item.confirm}
              answering={Boolean(answering)}
              error={answerError ?? null}
              onAnswer={onAnswer}
            />
          ) : null}

          <div className="whitespace-pre-wrap break-words">
            <Body text={item.content} />
            {item.streaming ? (
              <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-tint align-baseline" />
            ) : null}
          </div>
        </div>
        <div className="mt-1 px-1 font-mono text-[10px] text-muted/60">
          {isUser ? 'you' : 'luxion'}
          {item.createdAt ? ` · ${formatTime(item.createdAt)}` : ''}
          {item.streaming ? ' · streaming' : ''}
          {!isUser && item.confirm ? ' · waiting for approval' : ''}
          {!isUser && !item.confirm && hasActivity && !item.streaming ? ' · tools used' : ''}
        </div>
      </div>
    </div>
  )
}

function formatTime(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleTimeString()
}
