/**
 * Shared, mutable per-frame state for the 3D core.
 *
 * Everything lives in one object mutated inside `useFrame` so state changes
 * never trigger React re-renders while the scene is animating.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { AI_STATE_TUNING, useAIState, type AIState } from '../../lib/aiState'
import { useAppearance } from '../../lib/appearance'
import { useGraphics } from '../../lib/graphics'

export interface CoreDrive {
  time: number
  energy: number
  speed: number
  ringSpeed: number
  pulse: number
  expand: number
  parallaxX: number
  parallaxY: number
  /** 0 when prefers-reduced-motion is set, else 1 — gates every rotation. */
  motion: number
  color: THREE.Color
}

const DriveContext = createContext<CoreDrive | null>(null)

const TARGET_COLOR = new THREE.Color()

/** States that must keep their semantic colour regardless of the theme. */
const STATE_COLOR: Partial<Record<AIState, string>> = {
  success: '#34d399',
  warning: '#fbbf24',
  error: '#fb7185',
}

/** Everything else follows the accent chosen in Settings → Appearance. */
function targetColor(state: AIState, tint: string): THREE.Color {
  return TARGET_COLOR.set(STATE_COLOR[state] ?? tint)
}

export function CoreDriveProvider({ children }: { children: ReactNode }) {
  const drive = useMemo<CoreDrive>(
    () => ({
      time: 0,
      energy: 0.3,
      speed: 0.18,
      ringSpeed: 0.12,
      pulse: 0,
      expand: 0,
      parallaxX: 0,
      parallaxY: 0,
      motion: 1,
      color: new THREE.Color('#38bdf8'),
    }),
    [],
  )
  return <DriveContext.Provider value={drive}>{children}</DriveContext.Provider>
}

export function useDrive(): CoreDrive {
  const drive = useContext(DriveContext)
  if (!drive) throw new Error('useDrive must be used inside <CoreDriveProvider>')
  return drive
}

/** Pointer parallax — subtle, disabled under prefers-reduced-motion. */
function useParallax(drive: CoreDrive, enabled: boolean) {
  const target = useRef({ x: 0, y: 0 })

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      target.current.x = (event.clientX / window.innerWidth) * 2 - 1
      target.current.y = (event.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => window.removeEventListener('pointermove', onMove)
  }, [])

  return useCallback(
    (dt: number) => {
      const strength = enabled ? 1 : 0
      const lambda = 1.6
      drive.parallaxX = THREE.MathUtils.damp(
        drive.parallaxX,
        target.current.x * 0.16 * strength,
        lambda,
        dt,
      )
      drive.parallaxY = THREE.MathUtils.damp(
        drive.parallaxY,
        -target.current.y * 0.1 * strength,
        lambda,
        dt,
      )
    },
    [drive, enabled],
  )
}

/** Runs once per frame: eases energy/speed toward the current AI state. */
export function CoreController({ children }: { children: ReactNode }) {
  const drive = useDrive()
  const { state, clickNonce } = useAIState()
  const { reducedMotion } = useGraphics()
  const { accent } = useAppearance()
  const applyParallax = useParallax(drive, !reducedMotion)
  const lastClick = useRef(clickNonce)

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1)
    const tuning = AI_STATE_TUNING[state]
    // Reduced motion: the scene freezes entirely; only user-driven pulses
    // (which are opted into) still animate.
    const motion = reducedMotion ? 0 : 1
    drive.motion = motion

    if (clickNonce !== lastClick.current) {
      lastClick.current = clickNonce
      drive.pulse = 1
    }
    drive.pulse = Math.max(0, drive.pulse - dt * 1.6)

    drive.time += dt * (0.35 + drive.speed * 0.65) * motion
    drive.speed = THREE.MathUtils.damp(drive.speed, tuning.speed * motion, 2.2, dt)
    drive.ringSpeed = THREE.MathUtils.damp(drive.ringSpeed, tuning.ringSpeed * motion, 2.2, dt)
    drive.energy = THREE.MathUtils.damp(
      drive.energy,
      tuning.energy * 0.7 + drive.pulse * 0.6,
      2.8,
      dt,
    )
    drive.expand = THREE.MathUtils.damp(drive.expand, drive.pulse, 4.5, dt)
    drive.color.lerp(targetColor(state, accent.tint), 1 - Math.exp(-2 * dt))

    applyParallax(dt)
  })

  return <>{children}</>
}
