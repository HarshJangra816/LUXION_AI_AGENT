/**
 * Conversation + streaming chat API.
 *
 * Wire protocol (mirrors `backend/luxion/services/chat.py`):
 *   delta*  →  done | error
 */

import { API_BASE, errorFrom, request } from './api'
import { readSse } from './sse'
import type { ToolRisk, ToolRunStatus } from './tools'

export type ChatRole = 'system' | 'user' | 'assistant'

/**
 * What one turn actually sent (mirrors `luxion.context.ContextStats`).
 * All figures are estimates — provider-reported counts stay authoritative
 * for billing; this only shapes what we send (PRD §13-14).
 */
export interface ContextStats {
  budget_tokens: number
  reserve_tokens: number
  response_tokens: number
  spendable_tokens: number
  system_tokens: number
  summary_tokens: number
  history_tokens: number
  estimated_tokens: number
  messages_sent: number
  history_sent: number
  history_available: number
  history_dropped: number
  summarized: number
  truncated: boolean
  compression: 'none' | 'dropped' | 'summary'
}

export interface ConversationSummary {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}

/**
 * One tool run, as stored on the assistant message (`meta.tools`) so the
 * transcript still shows the activity after a reload (PRD §43).
 */
export interface ToolSummary {
  name: string
  status: ToolRunStatus
  risk: ToolRisk
  duration_ms: number | null
  error: string | null
  args: Record<string, unknown>
  output: string
}

export interface ChatMessageDto {
  id: number
  role: ChatRole
  content: string
  created_at: string
  tokens_in: number | null
  tokens_out: number | null
  /** USD spend reported by the provider (OpenRouter); null when not reported. */
  cost_usd: number | null
  /** Prompt composition behind this reply; null for older messages. */
  context: ContextStats | null
  /** Tool activity for this turn; null when nothing ran. */
  tools: ToolSummary[] | null
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessageDto[]
}

export interface TokenUsage {
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  /** Actual spend in USD — reported by OpenRouter, null elsewhere. */
  cost: number | null
  /** Prompt tokens served from the provider's cache. */
  cached_tokens: number | null
}

export interface ChatDelta {
  type: 'delta'
  text: string
}

export interface ChatDone {
  type: 'done'
  conversation_id: string
  message_id: number | null
  title: string | null
  finish_reason: string | null
  usage: TokenUsage | null
  model: string | null
  interrupted: boolean
  /** Estimated prompt composition for this turn (PRD §14). */
  context: ContextStats | null
  /** Compact record of every tool that ran this turn (PRD §43). */
  tools: ToolSummary[] | null
}

export type ChatToolPhase = 'start' | ToolRunStatus

/** One tool lifecycle step: `start` then a terminal phase. */
export interface ChatTool {
  type: 'tool'
  id: string
  name: string
  risk: ToolRisk
  phase: ChatToolPhase
  args: Record<string, unknown>
  output: string | null
  error: string | null
  duration_ms: number | null
}

/** Ask the user before running a `confirm`-level tool (PRD §21). */
export interface ChatConfirm {
  type: 'confirm'
  id: string
  name: string
  risk: ToolRisk
  args: Record<string, unknown>
  reason: string
  description: string
  expires_in_s: number
}

export interface ChatError {
  type: 'error'
  code: string
  message: string
  retryable: boolean
  message_id: number | null
}

export interface LlmStatus {
  provider: string
  label: string
  model: string
  base_url: string
  temperature: number
  max_tokens: number
  request_timeout_s: number
  api_key_configured: boolean
  api_key_env: string
  uses_default_system_prompt: boolean
  available_providers: { id: string; label: string; requires_api_key: boolean; local: boolean }[]
}

export interface LlmHealth {
  provider: string
  ok: boolean
  base_url: string
  models: string[]
  error: string | null
  latency_ms: number | null
}

const jsonBody = (payload: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

export function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>('/conversations', { signal })
}

export function createConversation(title?: string): Promise<ConversationSummary> {
  return request<ConversationSummary>(
    '/conversations',
    title === undefined ? { method: 'POST' } : jsonBody({ title }),
  )
}

export function getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${id}`, { signal })
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/conversations/${id}`, { method: 'DELETE' })
}

export function getLlmStatus(signal?: AbortSignal): Promise<LlmStatus> {
  return request<LlmStatus>('/llm/status', { signal })
}

export function getLlmHealth(signal?: AbortSignal): Promise<LlmHealth> {
  return request<LlmHealth>('/llm/health', { signal })
}

/**
 * Make an installed adapter active (Settings → tap an adapter). Omit `model`
 * to keep whatever the adapter already had; pass `''` to go back to auto-detect.
 * Returns the rebuilt status so the caller can update in one round trip.
 */
export function setLlmProvider(provider: string, model?: string): Promise<LlmStatus> {
  const payload = model === undefined ? { provider } : { provider, model }
  return request<LlmStatus>('/llm/provider', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Forget the Settings-page selection and fall back to `.env`. */
export function resetLlmProvider(): Promise<LlmStatus> {
  return request<LlmStatus>('/llm/provider', { method: 'DELETE' })
}

export interface StreamHandlers {
  onDelta: (delta: ChatDelta) => void
  onTool: (tool: ChatTool) => void
  onConfirm: (confirm: ChatConfirm) => void
  onDone: (done: ChatDone) => void
  onError: (error: ChatError) => void
}

/**
 * POST a user turn and forward each SSE frame to `handlers`.
 * Resolves when the server closes the stream (after `done` or `error`).
 */
export async function sendMessage(
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages`,
    { ...jsonBody({ content }), signal },
  )
  if (!response.ok) throw await errorFrom(response)

  for await (const frame of readSse(response)) {
    let payload: unknown
    try {
      payload = JSON.parse(frame.data)
    } catch {
      continue
    }
    if (frame.event === 'delta') handlers.onDelta(payload as ChatDelta)
    else if (frame.event === 'tool') handlers.onTool(payload as ChatTool)
    else if (frame.event === 'confirm') handlers.onConfirm(payload as ChatConfirm)
    else if (frame.event === 'done') {
      handlers.onDone(payload as ChatDone)
      return
    } else if (frame.event === 'error') {
      handlers.onError(payload as ChatError)
      return
    }
  }
}
