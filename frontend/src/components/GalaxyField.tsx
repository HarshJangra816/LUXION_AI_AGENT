/**
 * Background atmosphere layer — everything that fills the *blank* areas
 * around the blueprint core (never the core itself):
 *
 *  - two sheets of star dust, biased onto a galactic band through the core;
 *  - cool nebula clouds for depth;
 *  - an amber bokeh drift across the top of the view (the warm out-of-focus
 *    light look), slightly transparent and punched out around the core so it
 *    never sits on the orb.
 *
 * Pure CSS/JS (box-shadow star fields + blurred radial gradients) — no extra
 * WebGL pass, no new dependencies, deterministic seed so the sky never
 * flickers between renders. Lives inside AmbientBackground, i.e. below the
 * canvas and the readability scrim, so it can never compete with text.
 */


import { useMemo } from 'react'

type Rgb = readonly [number, number, number]

const STAR_COLORS: readonly Rgb[] = [
  [186, 230, 253], // pale cyan
  [191, 219, 254], // pale blue
  [255, 255, 255], // white
  [165, 180, 252], // periwinkle
  [254, 240, 199], // warm white
]


/* Galactic band anchor — matches the core's `top-[40%] left-[53.7%]`. */
const BAND_X = 53.7
const BAND_Y = 40
const BAND_SLOPE = 0.13

/** Core position, used to keep the bokeh off the orb. */
const CORE_X = '53.7%'
const CORE_Y = '40%'
const CORE_CLEARANCE = '320px'

const BOKEH_COLORS = [
  '#f59e0b',
  '#fbbf24',
  '#fb923c',
  '#fde047',
  '#ea580c',
  '#fcd34d',
  '#fdba74',
]

function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}


/*
 * @param bandShare 0–1 portion of stars clustered along the galactic band
 * @param alphaMin alpha window low bound
 * @param alphaMax alpha window high bound
 */

function starField(
  count: number,
  seed: number,
  bandShare: number,
  alphaMin: number,
  alphaMax: number,
): string {
  const rand = mulberry32(seed)
  const parts: string[] = []

  for (let i = 0; i < count; i += 1) {
    const x = rand() * 100
    let y: number

    if ((i % 100) / 100 < bandShare) {
      // Sum of three uniforms ≈ gaussian: denser in the band, sparse outside.
      const jitter = (rand() + rand() + rand() - 1.5) * 11
      y = BAND_Y + BAND_SLOPE * (x - BAND_X) + jitter
    } else {
      y = rand() * 100
    }

    const [r, g, b] = STAR_COLORS[Math.floor(rand() * STAR_COLORS.length)]
    const alpha = (alphaMin + rand() * (alphaMax - alphaMin)).toFixed(2)
    const blur = (rand() * 1.1).toFixed(2)
    const spread = (rand() * 0.35).toFixed(2)

    parts.push(
      `${x.toFixed(2)}vw ${Math.min(100, Math.max(0, y)).toFixed(2)}vh ` +
        `${blur}px ${spread}px rgba(${r}, ${g}, ${b}, ${alpha})`,
    )
  }

  return parts.join(', ')
}

interface Bokeh {
  x: number
  y: number
  size: number
  color: string
  alpha: number
}

/** Warm out-of-focus lights, densest across the top of the viewport. */
function bokehField(): Bokeh[] {
  const rand = mulberry32(0xb0c4)
  const blobs: Bokeh[] = []

  for (let i = 0; i < 26; i += 1) {
    blobs.push({
      x: 8 + Math.pow(rand(), 1.25) * 84,
      y: Math.pow(rand(), 1.7) * 46,
      size: 70 + rand() * 190,
      color: BOKEH_COLORS[Math.floor(rand() * BOKEH_COLORS.length)],
      alpha: 0.3 + rand() * 0.45,
    })
  }

  return blobs
}

function Nebula({ className, color }: { className: string; color: string }) {
  return (
    <div
      className={`absolute rounded-full blur-[110px] ${className}`}
      style={{ background: `radial-gradient(circle, ${color} 0%, transparent 70%)` }}
    />
  )
}

export function GalaxyField() {
  // Faint far dust + a brighter sheet with most stars hugging the band.
  const dust = useMemo(() => starField(260, 20260930, 0.55, 0.14, 0.42), [])
  const bright = useMemo(() => starField(90, 7, 0.75, 0.45, 0.95), [])
  const bokeh = useMemo(() => bokehField(), [])

  const fadeDown =
    'linear-gradient(to bottom, #000 0%, #000 24%, rgba(0,0,0,0.35) 48%, transparent 66%)'
  const coreHole = `radial-gradient(circle ${CORE_CLEARANCE} at ${CORE_X} ${CORE_Y}, transparent 0%, transparent 38%, #000 100%)`

  return (
    <div aria-hidden className="absolute inset-0 mix-blend-screen">
      {/* star dust — two sheets, slightly different twinkle cadence */} 
      <div
        className="lux-stars-a absolute top-0 left-0 size-0.5 rounded-full"
        style={{ boxShadow: dust }}
      />
      <div
        className="lux-stars-b absolute top-0 left-0 size-0.5 rounded-full"
        style={{ boxShadow: bright }}
      />

      {/* cool nebula clouds — kept off the top-left so the bokeh owns it */}
      <Nebula
        className="top-[46%] right-[-16%] size-[58vmin] opacity-60"
        color="rgba(14, 116, 144, 0.45)"
      />
      <Nebula
        className="bottom-[-24%] left-[24%] size-[54vmin] opacity-55"
        color="rgba(30, 64, 175, 0.42)"
      />

      {/* amber bokeh: blank areas only — fades out downward and is punched
          out around the core so it never lands on the orb */}
      <div
        className="absolute inset-0"
        style={{ maskImage: fadeDown, WebkitMaskImage: fadeDown }}
      >
        <div
          className="absolute inset-0"
          style={{ maskImage: coreHole, WebkitMaskImage: coreHole }}
        >
          <div className="absolute inset-0 opacity-65 blur-[24px]">
            {bokeh.map((blob, index) => (
              <span
                key={`${blob.color}-${index}`}
                className="absolute rounded-full"
                style={{
                  left: `${blob.x}%`,
                  top: `${blob.y}%`,
                  width: blob.size,
                  height: blob.size,
                  transform: 'translate(-50%, -50%)',
                  opacity: blob.alpha,
                  background: `radial-gradient(circle, ${blob.color} 0%, ${blob.color}d9 38%, transparent 72%)`,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
  
