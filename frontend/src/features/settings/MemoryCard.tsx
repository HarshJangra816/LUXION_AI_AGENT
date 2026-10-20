import { useCallback, useEffect, useState } from 'react'
import { AlertIcon, GaugeIcon, PlusIcon, RefreshIcon, TrashIcon } from '../../components/icons'
import { SettingsCard } from '../../components/SettingsCard'
import { useAIState } from '../../lib/aiState'
import { ApiError } from '../../lib/api'
import {
  clearMemories,
  createMemory,
  deleteMemory,
  getMemoryConfig,
  getRepositoryStatus,
  indexRepository,
  listMemories,
  MEMORY_KINDS,
  resetMemoryConfig,
  searchMemories,
  searchRepository,
  setMemoryConfig,
  type Memory,
  type MemoryConfigBundle,
  type MemoryKind,
  type MemorySearchResult,
  type RagConfig,
  type RepositorySearchResult,
  type RepositoryStatus,
} from '../../lib/memory'

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

/** A row of label + control in the same shape as the other settings cards. */
function Row({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="flex items-center justify-between gap-3 border-b border-white/8 py-2.5 last:border-b-0">
      <span className="min-w-0">
        <span className="block text-xs text-ink">{label}</span>
        {hint ? (
          <span className="block font-mono text-[10px] text-muted/70">{hint}</span>
        ) : null}
      </span>
      {children}
    </label>
  )
}

function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full border transition duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-tint/60 ${
        checked ? 'border-tint/60 bg-tint/30' : 'border-white/15 bg-white/8'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:border-tint/60'}`}
    >
      <span
        className={`absolute top-0.5 size-4 rounded-full transition duration-200 ${
          checked ? 'left-6 bg-tint' : 'left-0.5 bg-muted'
        }`}
      />
    </button>
  )
}

const NUM_CLASS =
  'h-8 w-24 shrink-0 rounded-lg border border-white/15 bg-surface/70 px-2 text-right font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

const SELECT_CLASS =
  'h-8 w-40 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60'

const KIND_CHIP: Record<string, string> = {
  fact: 'border-tint/40 text-tint',
  preference: 'border-status-ok/40 text-status-ok',
  task: 'border-warning/40 text-warning',
  project: 'border-white/25 text-muted',
  episode: 'border-white/25 text-muted',
}

export function MemoryCard() {
  const [bundle, setBundle] = useState<MemoryConfigBundle | null>(null)
  const [draft, setDraft] = useState<Partial<RagConfig>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { pulse } = useAIState()

  // stored memories
  const [memories, setMemories] = useState<Memory[]>([])
  const [memoryTotal, setMemoryTotal] = useState(0)
  const [kindFilter, setKindFilter] = useState<MemoryKind | ''>('')
  const [newText, setNewText] = useState('')
  const [newKind, setNewKind] = useState<MemoryKind>('fact')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchHits, setSearchHits] = useState<MemorySearchResult | null>(null)

  // repository index
  const [repo, setRepo] = useState<RepositoryStatus | null>(null)
  const [repoQuery, setRepoQuery] = useState('')
  const [repoResult, setRepoResult] = useState<RepositorySearchResult | null>(null)
  const [repoReport, setRepoReport] = useState<string | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextBundle, nextMemories, nextRepo] = await Promise.all([
        getMemoryConfig(signal),
        listMemories({ limit: 200 }, signal),
        getRepositoryStatus(signal),
      ])
      setBundle(nextBundle)
      setMemories(nextMemories.items)
      setMemoryTotal(nextMemories.total)
      setRepo(nextRepo)
      setError(null)
    } catch (caught) {
      if (signal?.aborted) return
      setError(messageOf(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const refreshMemories = useCallback(async (kind?: MemoryKind | '') => {
    const page = await listMemories({ kind: kind || undefined, limit: 200 })
    setMemories(page.items)
    setMemoryTotal(page.total)
  }, [])

  // ---------------------------------------------------------------- derived
  const config = bundle ? { ...bundle.config, ...draft } : null
  const dirtyCount = Object.keys(draft).length

  const setField = <K extends keyof RagConfig>(key: K, value: RagConfig[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
  }

  const num = (key: keyof RagConfig, min: number, max: number, step: number) => (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={String(config?.[key] ?? '')}
      disabled={busy !== null}
      onChange={(event) => {
        const value = Number(event.target.value)
        if (Number.isFinite(value)) setField(key, value as never)
      }}
      className={NUM_CLASS}
    />
  )

  // --------------------------------------------------------------- actions
  const addMemory = async () => {
    const text = newText.trim()
    if (!text || busy !== null) return
    setBusy('add')
    try {
      await createMemory({ text, kind: newKind })
      setNewText('')
      await refreshMemories(kindFilter)
      setSearchHits(null)
      setError(null)
      pulse('success', 1000)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const forgetMemory = async (id: number) => {
    if (busy !== null) return
    setBusy(`forget-${id}`)
    try {
      await deleteMemory(id)
      if (searchHits) {
        setSearchHits({
          ...searchHits,
          hits: searchHits.hits.filter((hit) => hit.id !== id),
        })
      }
      await refreshMemories(kindFilter)
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const forgetAll = async () => {
    if (busy !== null) return
    setBusy('clear')
    try {
      await clearMemories()
      setSearchHits(null)
      await refreshMemories(kindFilter)
      setError(null)
      pulse('success', 1200)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const runSearch = async () => {
    const query = searchQuery.trim()
    if (!query || busy !== null) return
    setBusy('search')
    try {
      setSearchHits(await searchMemories({ query, k: 6 }))
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const runRepoSearch = async () => {
    const query = repoQuery.trim()
    if (!query || busy !== null) return
    setBusy('repo-search')
    try {
      setRepoResult(await searchRepository({ query, k: 6, files: 5 }))
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1500)
    } finally {
      setBusy(null)
    }
  }

  const runIndex = async () => {
    if (busy !== null) return
    setBusy('index')
    setRepoReport(null)
    try {
      const report = await indexRepository()
      setRepoReport(
        `${report.indexed} indexed · ${report.unchanged} unchanged · ${report.skipped} skipped · ${report.failed} failed · ${report.chunks} chunks total`,
      )
      setRepo(await getRepositoryStatus())
      setBundle(await getMemoryConfig())
      setError(null)
      pulse('success', 1500)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    if (dirtyCount === 0 || busy !== null) return
    setBusy('save')
    try {
      setBundle(await setMemoryConfig(draft))
      setDraft({})
      setRepo(await getRepositoryStatus())
      setError(null)
      pulse('success', 1200)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setBusy(null)
    }
  }

  const revert = async () => {
    if (busy !== null) return
    setBusy('revert')
    try {
      setBundle(await resetMemoryConfig())
      setDraft({})
      setRepo(await getRepositoryStatus())
      setError(null)
      pulse('success', 1200)
    } catch (caught) {
      setError(messageOf(caught))
      pulse('error', 1600)
    } finally {
      setBusy(null)
    }
  }

  const pickKind = async (kind: MemoryKind | '') => {
    setKindFilter(kind)
    setSearchHits(null)
    try {
      await refreshMemories(kind)
      setError(null)
    } catch (caught) {
      setError(messageOf(caught))
    }
  }

  const shown = searchHits ? searchHits.hits : memories
  const currentModel = bundle?.embedding_models.find(
    (model) => model.id === config?.embedding_model,
  )

  return (
    <SettingsCard
      id="memory"
      title="Memory & knowledge"
      icon={<GaugeIcon className="size-4 text-tint" />}
      defaultOpen
      badge={
        bundle ? (
          <>
            <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-muted uppercase">
              {memoryTotal} memories · {bundle.chunks} chunks
            </span>
            {bundle.needs_reembed ? (
              <span className="rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-warning uppercase">
                re-embed needed
              </span>
            ) : null}
          </>
        ) : null
      }
      hint={
        <>
          What Luxion remembers about you and your projects, and how retrieval feeds chat turns
          (PRD §33.14, §58). Recalled memories and the files relevant to each question are injected
          into the system prompt — both streams share one char budget. Changes apply when you press{' '}
          <span className="text-ink">Save</span>.
        </>
      }
      actions={
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || busy !== null}
          className={`flex shrink-0 items-center gap-1.5 rounded-lg border border-white/15 px-3 py-1.5 text-xs transition duration-200 ${
            loading || busy !== null
              ? 'cursor-wait text-muted'
              : 'cursor-pointer text-muted hover:border-tint/60 hover:text-ink'
          }`}
        >
          <RefreshIcon className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      }
    >
      {error ? (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-xs text-danger">
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

      {loading && !config ? (
        <p className="mt-4 text-xs text-muted">Loading memory settings…</p>
      ) : null}

      {config && bundle ? (
        <>
          {/* ------------------------------------------------ memories */}
          <div className="mt-4 rounded-xl border border-white/10 bg-surface/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Stored memories
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={kindFilter}
                  disabled={busy !== null}
                  onChange={(event) => void pickKind(event.target.value as MemoryKind | '')}
                  className="h-8 w-32 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
                >
                  <option value="">All kinds</option>
                  {MEMORY_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {kind}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void forgetAll()}
                  disabled={busy !== null || memoryTotal === 0}
                  title="Forget every stored memory"
                  className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                    busy !== null || memoryTotal === 0
                      ? 'cursor-not-allowed border-white/10 text-muted/50'
                      : 'cursor-pointer border-white/15 text-muted hover:border-danger/50 hover:text-danger'
                  }`}
                >
                  {busy === 'clear' ? 'Clearing…' : 'Clear all'}
                </button>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                value={newText}
                disabled={busy !== null}
                placeholder="Remember that…"
                maxLength={2000}
                onChange={(event) => setNewText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void addMemory()
                }}
                className="h-8 min-w-0 flex-1 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
              />
              <select
                value={newKind}
                disabled={busy !== null}
                onChange={(event) => setNewKind(event.target.value as MemoryKind)}
                className="h-8 w-28 shrink-0 cursor-pointer rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
              >
                {MEMORY_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void addMemory()}
                disabled={busy !== null || !newText.trim()}
                className={`flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null || !newText.trim()
                    ? 'cursor-not-allowed border-white/10 text-muted/50'
                    : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
                }`}
              >
                <PlusIcon className="size-3.5" />
                {busy === 'add' ? 'Adding…' : 'Add'}
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/8 pt-3">
              <input
                value={searchQuery}
                disabled={busy !== null}
                placeholder="Search memories…"
                maxLength={500}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void runSearch()
                }}
                className="h-8 min-w-0 flex-1 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => void runSearch()}
                disabled={busy !== null || !searchQuery.trim()}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null || !searchQuery.trim()
                    ? 'cursor-not-allowed border-white/10 text-muted/50'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                }`}
              >
                {busy === 'search' ? 'Searching…' : 'Search'}
              </button>
              {searchHits ? (
                <button
                  type="button"
                  onClick={() => {
                    setSearchHits(null)
                    setSearchQuery('')
                  }}
                  className="cursor-pointer rounded-lg border border-white/15 px-3 py-1.5 text-xs text-muted transition duration-200 hover:border-tint/60 hover:text-ink"
                >
                  Show all
                </button>
              ) : null}
            </div>

            <div className="mt-3 max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {shown.length === 0 ? (
                <p className="py-2 text-center text-[11px] text-muted/70">
                  {searchHits
                    ? 'No memories matched that search.'
                    : 'Nothing stored yet — memories appear here as chats teach Luxion about you.'}
                </p>
              ) : (
                shown.map((memory) => (
                  <div
                    key={memory.id}
                    className="flex items-start gap-2 rounded-lg border border-white/8 bg-panel/40 px-3 py-2"
                  >
                    <span
                      className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wider uppercase ${
                        KIND_CHIP[memory.kind] ?? 'border-white/25 text-muted'
                      }`}
                    >
                      {memory.kind}
                    </span>
                    <span className="min-w-0 flex-1 text-[11px] leading-relaxed text-ink">
                      {memory.text}
                      {memory.score != null ? (
                        <span className="ml-1.5 font-mono text-[10px] text-muted/70">
                          score {memory.score.toFixed(2)}
                        </span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      onClick={() => void forgetMemory(memory.id)}
                      disabled={busy !== null}
                      title="Forget this memory"
                      className="mt-0.5 shrink-0 cursor-pointer rounded border border-white/10 p-1 text-muted transition duration-200 hover:border-danger/50 hover:text-danger disabled:cursor-wait disabled:opacity-50"
                    >
                      <TrashIcon className="size-3" />
                    </button>
                  </div>
                ))
              )}
            </div>
            {searchHits ? (
              <p className="mt-2 font-mono text-[10px] text-muted/70">
                {searchHits.hits.length} hit{searchHits.hits.length === 1 ? '' : 's'} · prompt
                preview: “{searchHits.preview.slice(0, 120)}…”
              </p>
            ) : (
              <p className="mt-2 font-mono text-[10px] text-muted/70">
                showing {shown.length} of {memoryTotal}
              </p>
            )}
          </div>

          {/* ------------------------------------- retrieval + injection */}
          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Context injection
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Recall memories" hint="inject recalled memories into every chat turn">
                  <Toggle
                    checked={config.inject_memory}
                    disabled={busy !== null}
                    onChange={(value) => setField('inject_memory', value)}
                    label="Inject memories into the system prompt"
                  />
                </Row>
                <Row
                  label="Repository context"
                  hint="inject the files relevant to the question"
                >
                  <Toggle
                    checked={config.inject_repository}
                    disabled={busy !== null}
                    onChange={(value) => setField('inject_repository', value)}
                    label="Inject repository context into the system prompt"
                  />
                </Row>
                <Row
                  label="Memory extraction"
                  hint="keep extracting durable facts from finished turns"
                >
                  <Toggle
                    checked={config.memory_extraction}
                    disabled={busy !== null}
                    onChange={(value) => setField('memory_extraction', value)}
                    label="Extract memories from conversations"
                  />
                </Row>
                <Row label="Memory ceiling" hint="hard cap on stored memories">
                  {num('memory_max', 10, 100_000, 10)}
                </Row>
              </div>
            </div>

            <div>
              <h4 className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                Retrieval &amp; embeddings
              </h4>
              <div className="mt-1 rounded-xl border border-white/10 bg-surface/60 px-4 py-1">
                <Row label="Retrieval" hint="off = nothing is indexed or recalled">
                  <Toggle
                    checked={config.enabled}
                    disabled={busy !== null}
                    onChange={(value) => setField('enabled', value)}
                    label="Retrieval enabled"
                  />
                </Row>
                <Row label="Embedding model" hint={currentModel ? `${currentModel.dim}d · ${currentModel.size_gb} GB · ${currentModel.languages}` : undefined}>
                  <select
                    value={config.embedding_model}
                    disabled={busy !== null}
                    onChange={(event) => setField('embedding_model', event.target.value)}
                    className={`${SELECT_CLASS} max-w-[16rem]`}
                  >
                    {bundle.embedding_models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                    {!bundle.embedding_models.some(
                      (model) => model.id === config.embedding_model,
                    ) ? (
                      <option value={config.embedding_model}>{config.embedding_model}</option>
                    ) : null}
                  </select>
                </Row>
                <Row label="Top K" hint="hits a query returns before ranking">
                  {num('top_k', 1, 50, 1)}
                </Row>
                <Row label="Min score" hint="cosine floor in 0..1 — below it a hit is dropped">
                  {num('min_score', 0, 1, 0.05)}
                </Row>
                <Row label="Chunk size" hint="prose window in chars">
                  {num('chunk_chars', 200, 4000, 50)}
                </Row>
                <Row label="Chunk overlap" hint="tail carried into the next chunk">
                  {num('chunk_overlap', 0, 1000, 10)}
                </Row>
              </div>
            </div>
          </div>

          {bundle.needs_reembed ? (
            <p className="mt-3 rounded-lg border border-warning/30 bg-warning/8 px-3 py-2 text-[11px] text-warning">
              Stored vectors were built with a different embedding model — retrieval falls back to
              keyword matches until the index is rebuilt with the selected model.
            </p>
          ) : null}

          {/* -------------------------------------------------- repository */}
          <div className="mt-5 rounded-xl border border-white/10 bg-surface/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
                  Repository index
                </span>
                <span className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[10px] text-muted">
                  {repo ? `${repo.files} files · ${repo.chunks} chunks` : '—'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => void runIndex()}
                disabled={busy !== null || repo?.enabled === false}
                title={
                  repo?.enabled === false
                    ? 'Enable retrieval on the Retrieval & embeddings row first'
                    : 'Walk the approved workspaces and update the index (incremental)'
                }
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null || repo?.enabled === false
                    ? 'cursor-not-allowed border-white/10 text-muted/50'
                    : 'cursor-pointer border-tint/40 text-tint hover:bg-tint/10'
                }`}
              >
                {busy === 'index' ? 'Indexing…' : 'Index files'}
              </button>
            </div>

            {repo ? (
              <p className="mt-2 truncate font-mono text-[10px] text-muted/70" title={repo.roots.join('\n')}>
                {repo.roots.length > 0 ? `root ${repo.roots.join(' · ')}` : 'no approved workspaces'}{' '}
                · {repo.extensions.slice(0, 8).join(' ')}
                {repo.extensions.length > 8 ? ' …' : ''}
              </p>
            ) : null}
            {repoReport ? (
              <p className="mt-2 rounded-lg border border-white/10 bg-panel/40 px-3 py-1.5 font-mono text-[10px] text-muted">
                {repoReport}
              </p>
            ) : null}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                value={repoQuery}
                disabled={busy !== null}
                placeholder="Preview retrieval over indexed files…"
                maxLength={500}
                onChange={(event) => setRepoQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void runRepoSearch()
                }}
                className="h-8 min-w-0 flex-1 rounded-lg border border-white/15 bg-surface/70 px-2 font-mono text-[11px] text-ink transition duration-200 hover:border-white/30 focus:border-tint/60 focus:outline-none disabled:cursor-wait disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => void runRepoSearch()}
                disabled={busy !== null || !repoQuery.trim()}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null || !repoQuery.trim()
                    ? 'cursor-not-allowed border-white/10 text-muted/50'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                }`}
              >
                {busy === 'repo-search' ? 'Searching…' : 'Search'}
              </button>
            </div>

            {repoResult ? (
              <div className="mt-3 max-h-40 space-y-1 overflow-y-auto pr-1">
                {repoResult.hits.length === 0 ? (
                  <p className="py-2 text-center text-[11px] text-muted/70">
                    No indexed chunk matched that query.
                  </p>
                ) : (
                  repoResult.hits.map((hit, index) => (
                    <div
                      key={`${hit.path}:${hit.start_line}:${index}`}
                      className="flex items-baseline gap-2 rounded-lg border border-white/8 bg-panel/40 px-3 py-1.5 font-mono text-[10px]"
                    >
                      <span className="min-w-0 flex-1 truncate text-ink" title={hit.path}>
                        {hit.path}:{hit.start_line}
                        {hit.end_line > hit.start_line ? `–${hit.end_line}` : ''}
                      </span>
                      <span className="shrink-0 text-muted/70">score {hit.score.toFixed(2)}</span>
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </div>

          {/* ------------------------------------------------------- actions */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
            <span className="font-mono text-[10px] text-muted/70">
              {dirtyCount === 0
                ? 'no pending changes'
                : `${dirtyCount} unsaved change${dirtyCount === 1 ? '' : 's'} → stored in rag.json`}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDraft({})}
                disabled={dirtyCount === 0 || busy !== null}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  dirtyCount === 0 || busy !== null
                    ? 'cursor-default border-white/10 text-muted/40'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
                }`}
              >
                Discard
              </button>
              <button
                type="button"
                onClick={() => void revert()}
                disabled={busy !== null}
                className={`rounded-lg border px-3 py-1.5 text-xs transition duration-200 ${
                  busy !== null
                    ? 'cursor-wait border-white/10 text-muted/50'
                    : 'cursor-pointer border-white/15 text-muted hover:border-danger/50 hover:text-danger'
                }`}
              >
                {busy === 'revert' ? 'Resetting…' : 'Reset to .env'}
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={dirtyCount === 0 || busy !== null}
                className={`rounded-lg px-4 py-1.5 text-xs transition duration-200 ${
                  dirtyCount === 0 || busy !== null
                    ? 'cursor-default bg-panel-2 text-muted/50'
                    : 'cursor-pointer bg-accent text-on-accent hover:brightness-110'
                }`}
              >
                {busy === 'save' ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </>
      ) : null}
    </SettingsCard>
  )
}
