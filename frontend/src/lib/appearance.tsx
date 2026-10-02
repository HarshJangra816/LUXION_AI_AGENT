/**
 * Appearance preferences — interface font, display font, type scale and the
 * accent/tint colour. Everything is persisted in localStorage and applied by
 * writing CSS custom properties on <html>, which the Tailwind `@theme` tokens
 * (src/index.css) read from.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type FontId = 'fira' | 'system' | 'serif' | 'verdana'
export type MonoId = 'fira-code' | 'system-mono'
export type SizeId = 'compact' | 'default' | 'large' | 'xl'

export interface Choice<T> {
  id: T
  label: string
  stack: string
  hint: string
}

export const UI_FONTS: Choice<FontId>[] = [
  {
    id: 'fira',
    label: 'Fira Sans',
    stack: "'Fira Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
    hint: 'shipped with Luxion',
  },
  {
    id: 'system',
    label: 'System UI',
    stack: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    hint: 'native platform feel',
  },
  {
    id: 'serif',
    label: 'Georgian Serif',
    stack: "Georgia, 'Times New Roman', Times, serif",
    hint: 'editorial / reading',
  },
  {
    id: 'verdana',
    label: 'Verdana',
    stack: 'Verdana, Geneva, Tahoma, sans-serif',
    hint: 'wide, high legibility',
  },
]

export const MONO_FONTS: Choice<MonoId>[] = [
  {
    id: 'fira-code',
    label: 'Fira Code',
    stack: "'Fira Code', 'Cascadia Code', Consolas, ui-monospace, monospace",
    hint: 'headings + code blocks',
  },
  {
    id: 'system-mono',
    label: 'System Mono',
    stack: "Consolas, 'Cascadia Mono', 'SF Mono', ui-monospace, monospace",
    hint: 'lighter weight',
  },
]

export interface SizeChoice {
  id: SizeId
  label: string
  px: number
  hint: string
}

export const SIZES: SizeChoice[] = [
  { id: 'compact', label: 'Compact', px: 14, hint: 'more on screen' },
  { id: 'default', label: 'Default', px: 16, hint: 'recommended' },
  { id: 'large', label: 'Large', px: 18, hint: 'easier reading' },
  { id: 'xl', label: 'Extra large', px: 20, hint: 'accessibility' },
]

export interface AccentChoice {
  id: string
  label: string
  /** Chrome: nav, focus, HUD, particles, borders. */
  tint: string
  /** CTA buttons. */
  accent: string
}

export const ACCENT_PRESETS: AccentChoice[] = [
  { id: 'blueprint', label: 'Blueprint', tint: '#38bdf8', accent: '#22c55e' },
  { id: 'cyan', label: 'Cyan', tint: '#22d3ee', accent: '#06b6d4' },
  { id: 'emerald', label: 'Emerald', tint: '#34d399', accent: '#10b981' },
  { id: 'violet', label: 'Violet', tint: '#a78bfa', accent: '#a855f7' },
  { id: 'rose', label: 'Rose', tint: '#fb7185', accent: '#f43f5e' },
]

const DEFAULTS = { font: 'fira', mono: 'fira-code', size: 'default', accent: 'blueprint' } as const

const KEYS = {
  font: 'luxion.appearance.font',
  mono: 'luxion.appearance.mono',
  size: 'luxion.appearance.size',
  accent: 'luxion.appearance.accent',
} as const

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = localStorage.getItem(key)
    if (stored && (allowed as readonly string[]).includes(stored)) return stored as T
  } catch {
    // storage blocked — fall back to defaults
  }
  return fallback
}

function resolveAccent(value: string): AccentChoice {
  const preset = ACCENT_PRESETS.find((choice) => choice.id === value)
  if (preset) return preset
  if (/^#[0-9a-f]{6}$/i.test(value)) return { id: value, label: 'Custom', tint: value, accent: value }
  return ACCENT_PRESETS[0]
}

interface AppearanceValue {
  font: FontId
  setFont: (value: FontId) => void
  mono: MonoId
  setMono: (value: MonoId) => void
  size: SizeId
  setSize: (value: SizeId) => void
  accentValue: string
  setAccentValue: (value: string) => void
  accent: AccentChoice
}

const AppearanceContext = createContext<AppearanceValue | null>(null)

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [font, setFont] = useState<FontId>(() =>
    read(KEYS.font, ['fira', 'system', 'serif', 'verdana'] as const, DEFAULTS.font),
  )
  const [mono, setMono] = useState<MonoId>(() =>
    read(KEYS.mono, ['fira-code', 'system-mono'] as const, DEFAULTS.mono),
  )
  const [size, setSize] = useState<SizeId>(() =>
    read(KEYS.size, ['compact', 'default', 'large', 'xl'] as const, DEFAULTS.size),
  )
  const [accentValue, setAccentValue] = useState<string>(() => {
    try {
      return localStorage.getItem(KEYS.accent) ?? DEFAULTS.accent
    } catch {
      return DEFAULTS.accent
    }
  })

  const accent = useMemo(() => resolveAccent(accentValue), [accentValue])
  const scale = SIZES.find((choice) => choice.id === size) ?? SIZES[1]

  useEffect(() => {
    const root = document.documentElement
    const ui = UI_FONTS.find((choice) => choice.id === font) ?? UI_FONTS[0]
    const display = MONO_FONTS.find((choice) => choice.id === mono) ?? MONO_FONTS[0]
    root.style.setProperty('--font-sans', ui.stack)
    root.style.setProperty('--font-mono', display.stack)
    root.style.setProperty('--lux-scale', `${scale.px}px`)
    root.style.setProperty('--color-tint', accent.tint)
    root.style.setProperty('--color-accent', accent.accent)
  }, [font, mono, scale.px, accent])

  useEffect(() => {
    try {
      localStorage.setItem(KEYS.font, font)
      localStorage.setItem(KEYS.mono, mono)
      localStorage.setItem(KEYS.size, size)
      localStorage.setItem(KEYS.accent, accentValue)
    } catch {
      // storage blocked — the session still honours the choice
    }
  }, [font, mono, size, accentValue])

  const value = useMemo(
    () => ({
      font,
      setFont,
      mono,
      setMono,
      size,
      setSize,
      accentValue,
      setAccentValue,
      accent,
    }),
    [font, mono, size, accentValue, accent],
  )

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>
}

export function useAppearance(): AppearanceValue {
  const value = useContext(AppearanceContext)
  if (!value) throw new Error('useAppearance must be used inside <AppearanceProvider>')
  return value
}
