/**
 * Graphics quality + motion preferences for the 3D core.
 *
 * Quality is auto-detected once (hardwareConcurrency / DPR) and can be
 * overridden from Settings; the choice persists in localStorage.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type Quality = 'high' | 'medium' | 'low'

export interface QualityProfile {
  dpr: [number, number]
  antialias: boolean
  particles: number
  shellSegments: number
  rings: number
  glowLayers: number
  detailRings: boolean
}

export const QUALITY_PROFILES: Record<Quality, QualityProfile> = {
  high: { dpr: [1, 2], antialias: true, particles: 1400, shellSegments: 5, rings: 7, glowLayers: 3, detailRings: true },
  medium: { dpr: [1, 1.5], antialias: false, particles: 800, shellSegments: 4, rings: 5, glowLayers: 2, detailRings: true },
  low: { dpr: [1, 1], antialias: false, particles: 350, shellSegments: 3, rings: 4, glowLayers: 1, detailRings: false },
}

const STORAGE_KEY = 'luxion.graphics.quality'
const BRIGHTNESS_KEY = 'luxion.graphics.brightness'

export const MIN_BRIGHTNESS = 0.4
export const MAX_BRIGHTNESS = 1
export const DEFAULT_BRIGHTNESS = 0.8

function detect(): Quality {
  const cores = navigator.hardwareConcurrency ?? 4
  const dpr = window.devicePixelRatio || 1
  if (cores >= 8 && dpr <= 2) return 'high'
  if (cores >= 4) return 'medium'
  return 'low'
}

function read(): Quality {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'high' || stored === 'medium' || stored === 'low') return stored
  } catch {
    // storage blocked; fall back to auto-detection
  }
  return detect()
}

function readBrightness(): number {
  try {
    const stored = Number.parseFloat(localStorage.getItem(BRIGHTNESS_KEY) ?? '')
    if (Number.isFinite(stored)) {
      return Math.min(MAX_BRIGHTNESS, Math.max(MIN_BRIGHTNESS, stored))
    }
  } catch {
    // storage blocked; fall back to the default
  }
  return DEFAULT_BRIGHTNESS
}

interface GraphicsValue {
  quality: Quality
  profile: QualityProfile
  setQuality: (next: Quality) => void
  /** Scene opacity (0.4–1) — keeps the glow from eating the interface. */
  brightness: number
  setBrightness: (next: number) => void
  reducedMotion: boolean
}

const GraphicsContext = createContext<GraphicsValue | null>(null)

export function GraphicsProvider({ children }: { children: ReactNode }) {
  const [quality, setQualityRaw] = useState<Quality>(() => read())
  const [brightness, setBrightnessRaw] = useState<number>(() => readBrightness())
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReducedMotion(media.matches)
    sync()
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])

  const setQuality = useCallback((next: Quality) => {
    setQualityRaw(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // ignore; the session still uses the new value
    }
  }, [])

  const setBrightness = useCallback((next: number) => {
    const clamped = Math.min(MAX_BRIGHTNESS, Math.max(MIN_BRIGHTNESS, next))
    setBrightnessRaw(clamped)
    try {
      localStorage.setItem(BRIGHTNESS_KEY, String(clamped))
    } catch {
      // ignore; the session still uses the new value
    }
  }, [])

  const value = useMemo(
    () => ({
      quality,
      profile: QUALITY_PROFILES[quality],
      setQuality,
      brightness,
      setBrightness,
      reducedMotion,
    }),
    [quality, setQuality, brightness, setBrightness, reducedMotion],
  )

  return <GraphicsContext.Provider value={value}>{children}</GraphicsContext.Provider>
}

export function useGraphics(): GraphicsValue {
  const value = useContext(GraphicsContext)
  if (!value) throw new Error('useGraphics must be used inside <GraphicsContext.Provider>')
  return value
}
