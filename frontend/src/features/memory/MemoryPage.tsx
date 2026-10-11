import { MemoryCard } from '../settings/MemoryCard'

/** Phase 5d surface — the same card Settings hosts, as its own page. */
export function MemoryPage() {
  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 md:px-8">
      <div>
        <h2 className="text-lg font-semibold text-ink">Memory &amp; knowledge</h2>
        <p className="mt-1 text-xs text-muted">
          What Luxion remembers, how retrieval ranks it, and which files feed chat context.
        </p>
      </div>
      <MemoryCard />
    </div>
  )
}
