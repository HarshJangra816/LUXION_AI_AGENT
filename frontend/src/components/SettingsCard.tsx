import { useCallback, useState, type ReactNode } from 'react'
import { ChevronIcon } from './icons'

const STORAGE_PREFIX = 'luxion.card.'

/** Last choice for `id`, or null when the user never touched this card. */
function readStored(id: string): boolean | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + id)
    return raw === null ? null : raw === '1'
  } catch {
    return null // private mode / storage blocked — just don't remember
  }
}

interface SettingsCardProps {
  /** Stable id — the open/closed choice is remembered per card in localStorage. */
  id: string
  title: string
  /** Small icon shown before the title. */
  icon?: ReactNode
  /** Status chips rendered after the title (stay visible while collapsed). */
  badge?: ReactNode
  /** Summary paragraph under the header — shown only while open. */
  hint?: ReactNode
  /** Header buttons (Refresh, Test, …) — clicking them does not toggle. */
  actions?: ReactNode
  /** Open on first visit (never touched before); the first card of a page. */
  defaultOpen?: boolean
  children: ReactNode
}

/**
 * Collapsible settings card. The header (icon + title + badge + chevron) is
 * one toggle button; `actions` sit outside it so a Refresh press never
 * collapses the card. The body stays mounted while collapsed (data already
 * loaded is kept) but is animation-hidden and `inert`, so nothing inside is
 * focusable until the card is open.
 */
export function SettingsCard({
  id,
  title,
  icon,
  badge,
  hint,
  actions,
  defaultOpen = false,
  children,
}: SettingsCardProps) {
  const [open, setOpen] = useState<boolean>(() => readStored(id) ?? defaultOpen)

  const toggle = useCallback(() => {
    setOpen((previous) => {
      const next = !previous
      try {
        window.localStorage.setItem(STORAGE_PREFIX + id, next ? '1' : '0')
      } catch {
        // storage blocked — the choice lives for this mount only
      }
      return next
    })
  }, [id])

  return (
    <section className="rounded-xl border border-white/12 bg-panel/75 p-5 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={`lux-card-${id}`}
          className="flex min-w-0 cursor-pointer items-center gap-2 rounded-lg text-left transition duration-200 focus-visible:ring-2 focus-visible:ring-tint/60 focus-visible:outline-none"
        >
          {icon}
          <h3 className="truncate text-sm font-semibold text-ink">{title}</h3>
          {badge}
          <ChevronIcon
            className={`size-3.5 shrink-0 text-muted transition-transform duration-200 ${
              open ? '' : '-rotate-90'
            }`}
          />
        </button>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>

      {open && hint ? <p className="mt-1.5 text-xs text-muted">{hint}</p> : null}

      <div
        id={`lux-card-${id}`}
        className={`grid transition-[grid-template-rows] duration-200 ease-out ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden" inert={!open}>
          {children}
        </div>
      </div>
    </section>
  )
}
