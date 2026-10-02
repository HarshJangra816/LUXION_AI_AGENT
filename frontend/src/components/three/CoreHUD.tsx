import { useEffect, useState } from 'react'

import { AI_STATE_LABEL, useAIState } from '../../lib/aiState'
import { useGraphics } from '../../lib/graphics'
import { useDrive } from './coreDrive'

function Label({
  className,
  kicker,
  value,
  tone = 'text-ink/90',
}: {
  className: string
  kicker: string
  value: string
  tone?: string
}) {
  return (
    <div
      className={`absolute flex items-center gap-2 rounded border border-white/10 bg-surface/75 px-2 py-1 font-mono backdrop-blur-md ${className}`}
    >
      <span className="size-1 rounded-full bg-tint" />
      <span className="text-[9px] tracking-[0.24em] text-tint uppercase">{kicker}</span>
      <span className={`text-[10px] tracking-[0.18em] uppercase ${tone}`}>{value}</span>
    </div>
  )
}

/**
 * Thin technical read-out around the core. Every number is real: backend
 * state, measured FPS and the live drive energy — nothing decorative.
 */
export function CoreHUD() {
  const { state } = useAIState()
  const { quality } = useGraphics()
  const drive = useDrive()
  const [fps, setFps] = useState(0)
  const [charge, setCharge] = useState(30)

  useEffect(() => {
    let frames = 0
    let last = performance.now()
    let raf = 0

    const tick = (now: number) => {
      frames += 1
      if (now - last >= 500) {
        setFps(Math.round((frames * 1000) / (now - last)))
        setCharge(Math.round(drive.energy * 100))
        frames = 0
        last = now
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [drive])

  const tone =
    state === 'error'
      ? 'text-danger'
      : state === 'warning'
        ? 'text-warning'
        : state === 'success'
          ? 'text-status-ok'
          : 'text-ink/90'

  return (
    <div
      aria-hidden
      /*
       * Sized to stay inside the dashboard's core band (46vh below the header):
       * top 36% ± min(160px, 15vh) always clears the content scroller beneath,
       * so these labels can never collide with the greeting / ask bar.
       * `.hud-parallax` recedes + vanishes as the content scrolls past.
       */
      className="absolute top-[36%] left-[calc(50%+7.5rem)] hidden h-[min(320px,30vh)] w-[min(820px,calc(100vw-17rem))] -translate-x-1/2 -translate-y-1/2 md:block"
    >
      <div className="hud-parallax absolute inset-0">
        <span className="absolute top-0 left-0 h-6 w-6 border-t border-l border-tint/40" />
        <span className="absolute top-0 right-0 h-6 w-6 border-t border-r border-tint/40" />
        <span className="absolute bottom-0 left-0 h-6 w-6 border-b border-l border-tint/40" />
        <span className="absolute right-0 bottom-0 h-6 w-6 border-r border-b border-tint/40" />

        <span className="absolute top-[30%] left-[6%] h-px w-[14%] bg-gradient-to-r from-tint/0 to-tint/50" />
        <span className="absolute top-[64%] right-[6%] h-px w-[14%] bg-gradient-to-l from-tint/0 to-tint/50" />

        {/* Left column shares MODE's top row and CHARGE's bottom row. */}
        <Label className="top-1 left-10" kicker="SYS" value="CORE ONLINE" tone="text-status-ok" />
        <Label className="top-1 right-10" kicker="MODE" value={AI_STATE_LABEL[state]} tone={tone} />
        <Label
          className="bottom-1 left-10"
          kicker="RENDER"
          value={`${quality.toUpperCase()} · ${fps} FPS`}
        />
        <Label className="right-10 bottom-1" kicker="CHARGE" value={`${charge}%`} />
      </div>
    </div>
  )
}
