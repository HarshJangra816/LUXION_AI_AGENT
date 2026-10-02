import type { ReactNode } from 'react'

/**
 * Translucent surface used for every content block so the 3D core stays
 * visible behind the UI (design system: glassmorphism).
 */
export function GlassPanel({
  children,
  className,
  label,
}: {
  children: ReactNode
  className?: string
  label?: string
}) {
  return (
    <section
      className={`border border-white/12 bg-panel/10 shadow-[0_16px_44px_-22px_rgba(255,255,255,0.08)] backdrop-blur-xl transition duration-200 ${className ?? ''}`}
    >
      {label ? (
        <header className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
          <span className="size-1.5 rounded-full bg-tint" />
          <span className="font-mono text-[10px] tracking-[0.18em] text-tint uppercase">
            {label}
          </span>
        </header>
      ) : null}
      {children}
    </section>
  )
}
