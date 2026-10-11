/**
 * Memory CRUD, search, RAG config and repository index access.
 *
 * Powers the Settings → Memory card (PRD §32/§33.14) and the Knowledge
 * surface. Mirrors `backend/luxion/api/routes/memory.py` and
 * `repository.py`; the chat surface uses the `remember`/`recall`/`forget`
 * tools instead (same store, same index).
 */

import { request } from './api'

/** Every kind `remember`/`POST /memory` accepts (backend MEMORY_KINDS). */
export const MEMORY_KINDS = [
  'fact',
  'preference',
  'task',
  'project',
  'episode',
] as const
export type MemoryKind = (typeof MEMORY_KINDS)[number]

export interface Memory {
  id: number
  kind: string
  text: string
  source: string
  importance: number
  conversation_id?: string | null
  created_at?: string | null
  /** Only set on search results (PRD §16 ranking). */
  score?: number | null
}

export interface MemoryList {
  items: Memory[]
  total: number
  kind?: string | null
}

export interface MemorySearchResult {
  query: string
  hits: Memory[]
  /** Prompt-ready `- [kind] text` block (PRD §58). */
  preview: string
}

/** Every knob `PUT /memory/config` accepts (PRD §32 Settings → Memory). */
export interface RagConfig {
  enabled: boolean
  provider: string
  embedding_model: string
  chunk_chars: number
  chunk_overlap: number
  top_k: number
  min_score: number
  index_extensions: string[]
  exclude: string[]
  max_file_bytes: number
  max_files: number
  index_on_start: boolean
  reembed_batch: number
  memory_extraction: boolean
  memory_max: number
  inject_memory: boolean
  inject_repository: boolean
}

/** One model offered by the embedding dropdown (PRD §16). */
export interface EmbeddingModelSpec {
  id: string
  label: string
  dim: number
  size_gb: number
  languages: string
}

/** What Settings → Memory edits (effective + defaults + index health). */
export interface MemoryConfigBundle {
  config: RagConfig
  defaults: RagConfig
  /** The index was built with a different embedding model — warn the user. */
  needs_reembed: boolean
  chunks: number
  vectors: number
  embedding_models: EmbeddingModelSpec[]
}

/** What `GET /repository` reports about the index and walk policy. */
export interface RepositoryStatus {
  enabled: boolean
  roots: string[]
  files: number
  chunks: number
  extensions: string[]
  exclude: string[]
  index_on_start: boolean
}

/** Result of one incremental sync pass. */
export interface RepositoryIndexReport {
  roots: string[]
  scanned: number
  indexed: number
  unchanged: number
  skipped: number
  failed: number
  removed: number
  written: number
  chunks: number
  files: number
  changed: number
  indexed_at?: string | null
}

/** One retrieved chunk: file path + the lines it covers (PRD §17). */
export interface RepositoryHit {
  path: string
  source_type: string
  language: string
  start_line: number
  end_line: number
  score: number
  text: string
}

/** A hit grouped with its file — "start here" (PRD §17 relevant files). */
export interface RepositoryFile {
  path: string
  source_type: string
  language: string
  score: number
  range: string
  preview: string
}

export interface RepositorySearchResult {
  query: string
  hits: RepositoryHit[]
  files: RepositoryFile[]
  /** Prompt-ready `- path:lines` block (PRD §16). */
  preview: string
}

export interface MemoryListParams {
  kind?: MemoryKind | ''
  limit?: number
  offset?: number
}

/** List stored memories, newest first (`kind` filters by kind). */
export function listMemories(
  params: MemoryListParams = {},
  signal?: AbortSignal,
): Promise<MemoryList> {
  const query = new URLSearchParams()
  if (params.kind) query.set('kind', params.kind)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  return request<MemoryList>(`/memory${qs ? `?${qs}` : ''}`, { signal })
}

/** Store one standalone statement (`kind` defaults to `fact`). */
export function createMemory(payload: {
  text: string
  kind?: MemoryKind
  importance?: number
}): Promise<Memory> {
  return request<Memory>('/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Hybrid (vector + keyword) search over stored memories (PRD §16). */
export function searchMemories(payload: {
  query: string
  k?: number
  min_score?: number
  kinds?: MemoryKind[]
}): Promise<MemorySearchResult> {
  return request<MemorySearchResult>('/memory/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Forget one memory (and its indexed copy). */
export function deleteMemory(id: number): Promise<void> {
  return request<void>(`/memory/${id}`, { method: 'DELETE' })
}

/** Settings → Memory → "Clear all". */
export function clearMemories(): Promise<{ deleted: number }> {
  return request<{ deleted: number }>('/memory', { method: 'DELETE' })
}

/** Effective memory/RAG settings (defaults → `.env` → `rag.json`) + health. */
export function getMemoryConfig(signal?: AbortSignal): Promise<MemoryConfigBundle> {
  return request<MemoryConfigBundle>('/memory/config', { signal })
}

/** Persist the Settings → Memory edits (embedding model included). */
export function setMemoryConfig(
  patch: Partial<RagConfig>,
): Promise<MemoryConfigBundle> {
  return request<MemoryConfigBundle>('/memory/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `rag.json` so `.env` / built-in defaults win again. */
export function resetMemoryConfig(): Promise<MemoryConfigBundle> {
  return request<MemoryConfigBundle>('/memory/config', { method: 'DELETE' })
}

/** What is indexed, from where (Knowledge surface). */
export function getRepositoryStatus(signal?: AbortSignal): Promise<RepositoryStatus> {
  return request<RepositoryStatus>('/repository', { signal })
}

/** Run one incremental sync (the "Index files" button). */
export function indexRepository(): Promise<RepositoryIndexReport> {
  return request<RepositoryIndexReport>('/repository/index', { method: 'POST' })
}

/** The same hybrid search the `search_code` tool uses, for UI preview. */
export function searchRepository(payload: {
  query: string
  k?: number
  min_score?: number
  files?: number
}): Promise<RepositorySearchResult> {
  return request<RepositorySearchResult>('/repository/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
