import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertIcon, ChatIcon } from '../../components/icons'
import { ApiError } from '../../lib/api'
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  sendMessage,
  type ChatDone,
  type ChatMessageDto,
  type ChatTool,
  type ContextStats,
  type ConversationSummary,
} from '../../lib/chat'
import { resolveConfirmation } from '../../lib/tools'
import { Composer } from './Composer'
import { ConversationList } from './ConversationList'
import { MessageBubble, type ChatItem, type ToolRunView } from './MessageBubble'
import { Logo } from '../../components/Logo'
import { useAIState } from '../../lib/aiState'
import { formatTokens } from '../../lib/usage'

const SUGGESTIONS = [
  'What can you do in Phase 1?',
  'Explain the LLM provider abstraction',
  'Draft a short status update',
]

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

/** Token/cost figures of the most recent completed turn. */
interface LastUsage {
  prompt: number
  completion: number
  cost: number | null
  /** Prompt composition behind the last reply (Phase 2 context budget). */
  context: ContextStats | null
}

/** Newest assistant message that reported usage wins. */
function deriveUsage(messages: ChatMessageDto[]): LastUsage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role === 'assistant' && message.tokens_out != null) {
      return {
        prompt: message.tokens_in ?? 0,
        completion: message.tokens_out,
        cost: message.cost_usd ?? null,
        context: message.context,
      }
    }
  }
  return null
}

/** Hydrate stored messages into renderable items, tools included. */
function toItems(messages: ChatMessageDto[]): ChatItem[] {
  return messages.map((message) => ({
    key: `m-${message.id}`,
    role: message.role === 'user' ? 'user' : 'assistant',
    content: message.content,
    createdAt: message.created_at,
    tools: message.tools?.length ? message.tools : undefined,
  }))
}

/** Fold one `tool` SSE frame into the item's run list. */
function applyToolEvent(tools: ToolRunView[] | undefined, event: ChatTool): ToolRunView[] {
  const next = [...(tools ?? [])]
  const view: ToolRunView = {
    id: event.id,
    name: event.name,
    status: event.phase,
    risk: event.risk,
    duration_ms: event.duration_ms,
    error: event.error,
    args: event.args,
    output: event.output ?? '',
  }
  const index = next.findIndex((item) => item.id && item.id === event.id)
  if (index >= 0) next[index] = view
  else next.push(view)
  return next
}

function formatUsage(usage: LastUsage): string {
  const parts = [`${usage.prompt.toLocaleString()} in`, `${usage.completion.toLocaleString()} out`]
  if (usage.context) {
    parts.push(
      `ctx ${formatTokens(usage.context.estimated_tokens)}/${formatTokens(usage.context.budget_tokens)}`,
    )
  }
  if (usage.cost != null) parts.push(`$${usage.cost.toFixed(4)}`)
  return `${parts.join(' · ')} tok`
}

export function ChatPage({ initialDraft = '' }: { initialDraft?: string }) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [items, setItems] = useState<ChatItem[]>([])
  const [loadedId, setLoadedId] = useState<string | null>(null)
  const [draft, setDraft] = useState(initialDraft)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [listOpen, setListOpen] = useState(false)
  const [lastUsage, setLastUsage] = useState<LastUsage | null>(null)
  /** True while a tool confirmation Allow/Deny request is in flight. */
  const [answering, setAnswering] = useState(false)
  const [answerError, setAnswerError] = useState<string | null>(null)

  const { setState: setAIState, pulse } = useAIState()
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  /** True while the active conversation's history has not arrived yet. */
  const historyLoading = activeId !== null && loadedId !== activeId

  const refreshList = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await listConversations(signal)
      setConversations(data)
      setListError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setListError(messageOf(caught))
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void refreshList(controller.signal)
    return () => controller.abort()
  }, [refreshList])

  useEffect(() => {
    if (!activeId) return
    const controller = new AbortController()
    getConversation(activeId, controller.signal)
      .then((detail) => {
        setItems(toItems(detail.messages))
        setLastUsage(deriveUsage(detail.messages))
        setError(null)
        setLoadedId(activeId)
        setAIState('idle')
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(messageOf(caught))
        setItems([])
        setLastUsage(null)
        setLoadedId(activeId)
        pulse('error', 1500)
      })
    return () => controller.abort()
  }, [activeId, setAIState, pulse])

  useEffect(() => {
    const container = scrollRef.current
    if (container) container.scrollTop = container.scrollHeight
  }, [items, historyLoading])

  const handleDone = useCallback(
    (done: ChatDone) => {
      if (done.title) void refreshList()
      if (done.usage || done.context) {
        setLastUsage((previous) => ({
          prompt: done.usage?.prompt_tokens ?? previous?.prompt ?? 0,
          completion: done.usage?.completion_tokens ?? previous?.completion ?? 0,
          cost: done.usage?.cost ?? previous?.cost ?? null,
          context: done.context ?? previous?.context ?? null,
        }))
      }
    },
    [refreshList],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  /**
   * Answer a `confirm` prompt. The backend is already parked inside the agent
   * loop waiting on this id, so the reply only unblocks it — the follow-up
   * `tool` frame then updates the same bubble.
   */
  const answer = useCallback(
    async (confirmationId: string, approved: boolean) => {
      setAnswering(true)
      setAnswerError(null)
      try {
        await resolveConfirmation(confirmationId, approved)
        setItems((previous) =>
          previous.map((item) =>
            item.confirm?.id === confirmationId ? { ...item, confirm: null } : item,
          ),
        )
        setAIState(approved ? 'working' : 'warning')
      } catch (caught) {
        // A 404 means the prompt expired or was already answered elsewhere.
        setAnswerError(messageOf(caught))
        setItems((previous) =>
          previous.map((item) =>
            item.confirm?.id === confirmationId ? { ...item, confirm: null } : item,
          ),
        )
      } finally {
        setAnswering(false)
      }
    },
    [setAIState],
  )

  const reloadMessages = useCallback((conversationId: string) => {
    getConversation(conversationId)
      .then((detail) => {
        setItems(toItems(detail.messages))
        setLastUsage(deriveUsage(detail.messages))
      })
      .catch(() => undefined)
  }, [])

  const send = useCallback(
    async (text: string) => {
      const content = text.trim()
      if (!content || busy) return

      setError(null)
      setDraft('')
      setBusy(true)
      setAIState('thinking')

      let pulsed = false
      let firstDelta = true

      const now = Date.now()
      setItems((previous) => [
        ...previous,
        { key: `u-${now}`, role: 'user', content, createdAt: new Date().toISOString() },
      ])

      const controller = new AbortController()
      abortRef.current = controller

      let conversationId = activeId
      const assistantKey = `a-${now}`
      let created = false

      try {
        if (!conversationId) {
          const conversation = await createConversation()
          conversationId = conversation.id
          created = true
          setActiveId(conversation.id)
          setLastUsage(null)
          void refreshList()
        }

        setItems((previous) => [
          ...previous,
          { key: assistantKey, role: 'assistant', content: '', streaming: true },
        ])

        await sendMessage(
          conversationId,
          content,
          {
            onDelta: (delta) => {
              if (firstDelta) {
                firstDelta = false
                setAIState('speaking')
              }
              setItems((previous) =>
                previous.map((item) =>
                  item.key === assistantKey
                    ? { ...item, content: item.content + delta.text }
                    : item,
                ),
              )
            },
            onTool: (tool) => {
              if (tool.phase === 'start') setAIState('working')
              setItems((previous) =>
                previous.map((item) =>
                  item.key === assistantKey
                    ? { ...item, tools: applyToolEvent(item.tools, tool) }
                    : item,
                ),
              )
            },
            onConfirm: (confirm) => {
              setAIState('warning')
              setAnswerError(null)
              setItems((previous) =>
                previous.map((item) =>
                  item.key === assistantKey ? { ...item, confirm, tools: item.tools } : item,
                ),
              )
            },
            onDone: (done) => {
              setItems((previous) =>
                previous.map((item) =>
                  item.key === assistantKey
                    ? { ...item, streaming: false, confirm: null }
                    : item,
                ),
              )
              pulsed = true
              pulse('success', 1400)
              handleDone(done)
            },
            onError: (streamError) => {
              setItems((previous) =>
                previous.map((item) =>
                  item.key === assistantKey
                    ? { ...item, streaming: false, confirm: null }
                    : item,
                ),
              )
              setError(streamError.message)
              pulsed = true
              pulse('error', 1700)
            },
          },
          controller.signal,
        )
      } catch (caught) {
        setItems((previous) =>
          previous.map((item) =>
            item.key === assistantKey && item.streaming ? { ...item, streaming: false } : item,
          ),
        )
        if (isAbort(caught)) {
          // The backend persisted whatever had streamed; reload to show it.
          if (conversationId && !created) void reloadMessages(conversationId)
        } else if (created && conversationId) {
          // Creation succeeded but the turn failed: drop the empty thread.
          await deleteConversation(conversationId).catch(() => undefined)
          setActiveId(null)
          setItems([])
          void refreshList()
          setError(messageOf(caught))
          pulsed = true
          pulse('error', 1700)
        } else {
          setError(messageOf(caught))
          pulsed = true
          pulse('error', 1700)
        }
      } finally {
        abortRef.current = null
        setBusy(false)
        if (!pulsed) setAIState('idle')
      }
    },
    [activeId, busy, handleDone, pulse, refreshList, reloadMessages, setAIState],
  )

  async function handleSelect(id: string) {
    if (busy) stop()
    setListOpen(false)
    setAIState('thinking')
    setActiveId(id)
  }

  function handleNew() {
    if (busy) stop()
    setListOpen(false)
    setActiveId(null)
    setItems([])
    setError(null)
    setDraft('')
    setLastUsage(null)
    setAIState('idle')
  }

  async function handleDelete(id: string) {
    const wasActive = id === activeId
    if (wasActive && busy) stop()
    try {
      await deleteConversation(id)
    } catch (caught) {
      setError(messageOf(caught))
      return
    }
    setConversations((previous) => previous.filter((item) => item.id !== id))
    if (wasActive) {
      setActiveId(null)
      setItems([])
      setLastUsage(null)
    }
  }

  const active = conversations.find((conversation) => conversation.id === activeId)
  const title = active?.title ?? 'New conversation'
  const showEmpty = !historyLoading && items.length === 0

  const list = (
    <ConversationList
      conversations={conversations}
      activeId={activeId}
      loading={listLoading}
      error={listError}
      onSelect={(id) => void handleSelect(id)}
      onNew={handleNew}
      onDelete={(id) => void handleDelete(id)}
    />
  )

  return (
    <div className="relative flex min-h-0 flex-1">
      <aside className="hidden w-72 shrink-0 flex-col border-r border-white/10 bg-panel/80 md:flex">
        {list}
      </aside>

      {listOpen ? (
        <div className="absolute inset-0 z-30 md:hidden">
          <button
            type="button"
            aria-label="Close conversation list"
            onClick={() => setListOpen(false)}
            className="absolute inset-0 cursor-pointer bg-black/50 backdrop-blur-sm"
          />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-white/10 bg-surface shadow-xl">
            {list}
          </div>
        </div>
      ) : null}

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-white/10 bg-panel/75 px-4 py-3 backdrop-blur-xl md:px-6">
          <button
            type="button"
            onClick={() => setListOpen(true)}
            aria-label="Open conversation list"
            className="flex size-9 cursor-pointer items-center justify-center rounded-lg border border-white/15 text-muted transition duration-200 hover:text-ink md:hidden"
          >
            <ChatIcon className="size-4" />
          </button>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
            <p className="truncate font-mono text-[10px] text-muted/70">
              {busy
                ? 'generating…'
                : lastUsage
                  ? `${items.length} turns · ${formatUsage(lastUsage)}`
                  : `${items.length} turns in view`}
            </p>
          </div>
        </header>

        {error ? (
          <div className="flex items-start gap-2 border-b border-danger/30 bg-danger/10 px-4 py-2.5 text-xs text-danger md:px-6">
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

        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto bg-surface/75 px-4 py-6 md:px-6"
        >
          {historyLoading ? (
            <p className="text-sm text-muted">Loading conversation…</p>
          ) : showEmpty ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center gap-5 text-center">
              <Logo size={48} glow />
              <div>
                <h3 className="text-base font-semibold text-ink">Luxion is listening</h3>
                <p className="mt-1.5 text-sm text-muted">
                  Ask anything — replies stream in as the model generates them.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setDraft(suggestion)}
                    className="cursor-pointer rounded-lg border border-white/15 bg-panel/70 px-3 py-2 text-xs text-muted transition duration-200 hover:border-tint/60 hover:text-ink"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-5">
              {items.map((item) => (
                <MessageBubble
                  key={item.key}
                  item={item}
                  onAnswer={(id, approved) => void answer(id, approved)}
                  answering={answering}
                  answerError={answerError}
                />
              ))}
            </div>
          )}
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => void send(draft)}
          onStop={stop}
          busy={busy}
        />
      </section>
    </div>
  )
}
