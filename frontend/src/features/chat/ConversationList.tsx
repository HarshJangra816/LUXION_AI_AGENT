import { ChatIcon, PlusIcon, TrashIcon } from '../../components/icons'
import type { ConversationSummary } from '../../lib/chat'

interface ConversationListProps {
  conversations: ConversationSummary[]
  activeId: string | null
  loading: boolean
  error: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

export function ConversationList({
  conversations,
  activeId,
  loading,
  error,
  onSelect,
  onNew,
  onDelete,
}: ConversationListProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
        <span className="text-xs uppercase tracking-wider text-muted">Conversations</span>
        <button
          type="button"
          onClick={onNew}
          className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-white/15 bg-panel-2/60 px-2.5 py-1.5 text-xs text-ink transition duration-200 hover:border-tint/60 hover:text-tint"
        >
          <PlusIcon className="size-3.5" />
          New chat
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading ? (
          <p className="px-3 py-4 text-xs text-muted">Loading conversations…</p>
        ) : error ? (
          <p className="px-3 py-4 text-xs text-danger">{error}</p>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <ChatIcon className="size-5 text-muted/60" />
            <p className="text-xs text-muted">No conversations yet.</p>
            <p className="text-[11px] text-muted/60">Send a message to start one.</p>
          </div>
        ) : (
          <ul className="flex flex-col gap-1">
            {conversations.map((conversation) => {
              const active = conversation.id === activeId
              return (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(conversation.id)}
                    className={`w-full cursor-pointer rounded-lg py-2.5 pr-9 pl-3 text-left transition duration-200 ${
                      active
                        ? 'bg-panel-2 text-ink'
                        : 'text-muted hover:bg-panel-2/60 hover:text-ink'
                    }`}
                  >
                    <span className="block truncate text-sm">
                      {conversation.title ?? 'Untitled conversation'}
                    </span>
                    <span className="mt-0.5 block font-mono text-[10px] text-muted/60">
                      {conversation.message_count} messages
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(conversation.id)}
                    aria-label="Delete conversation"
                    title="Delete conversation"
                    className="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-muted opacity-0 transition duration-200 group-hover:opacity-100 hover:bg-danger/15 hover:text-danger focus-visible:opacity-100"
                  >
                    <TrashIcon className="size-4" />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </nav>
    </div>
  )
}
