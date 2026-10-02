/**
 * Token spend and context-window reporting (`/api/usage`).
 *
 * Mirrors `backend/luxion/services/usage.py`: totals come from the token
 * columns, USD cost and the per-turn context composition come from
 * `messages.meta`.
 */

import { request } from './api'
import type { ContextStats } from './chat'

export interface ContextBudget {
  total: number
  reserve: number
  response: number
  spendable: number
  keep_recent_messages: number
  summary_enabled: boolean
  summary_max_tokens: number
  max_history_messages: number
}

export interface TokenTotals {
  messages: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
}

export interface UsageTotals extends TokenTotals {
  conversations: number
}

export interface ConversationUsage extends TokenTotals {
  id: string
  title: string | null
}

export interface RecentTurn {
  conversation_id: string
  title: string | null
  message_id: number
  created_at: string
  tokens_in: number | null
  tokens_out: number | null
  cost_usd: number | null
  context: ContextStats | null
}

export interface UsageReport {
  budget: ContextBudget
  totals: UsageTotals
  conversations: ConversationUsage[]
  recent_turns: RecentTurn[]
}

export interface SummaryState {
  present: boolean
  tokens: number
  covered_through: number
  updated_at: string | null
}

export interface ConversationContextReport {
  conversation_id: string
  title: string | null
  totals: TokenTotals
  summary: SummaryState
  /** What the next turn would send (a read-only preview). */
  context: ContextStats
  budget: ContextBudget
}

export function getUsage(signal?: AbortSignal): Promise<UsageReport> {
  return request<UsageReport>('/usage', { signal })
}

export function getConversationContext(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationContextReport> {
  return request<ConversationContextReport>(`/usage/${encodeURIComponent(conversationId)}`, {
    signal,
  })
}

/** Compact token label: `940`, `4.1k`, `1.2M`. */
export function formatTokens(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (magnitude >= 10_000) return `${(value / 1_000).toFixed(1)}k`
  return Math.round(value).toLocaleString('en-US')
}

/** USD spend, or `null` when the provider does not report cost. */
export function formatCost(usd: number | null | undefined): string | null {
  if (usd == null || usd <= 0) return null
  return usd >= 0.01 ? `$${usd.toFixed(2)}` : `$${usd.toFixed(4)}`
}
