import type { BackendState } from '../lib/api'

export function StatusDot({ state }: { state: BackendState }) {
  const color =
    state.kind === 'online'
      ? 'bg-status-ok'
      : state.kind === 'offline'
        ? 'bg-danger'
        : 'bg-warning animate-pulse'
  return <span className={`inline-block size-2.5 rounded-full ${color}`} />
}
