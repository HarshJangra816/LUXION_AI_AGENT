import { useState } from 'react'

/**
 * Product mark.
 *
 * `import.meta.env.BASE_URL + 'logo.png'` is checked first — drop the real
 * logo at `frontend/public/logo.png` and it is used everywhere automatically.
 * Until then a geometric placeholder (clearly not the final artwork) renders.
 */
export function Logo({
  size = 32,
  className,
  glow = false,
}: {
  size?: number
  className?: string
  glow?: boolean
}) {
  const [failed, setFailed] = useState(false)

  if (!failed) {
    return (
      <img
        src={`${import.meta.env.BASE_URL}logo.png`}
        alt="Luxion"
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className={`shrink-0 object-contain ${glow ? 'drop-shadow-[0_0_10px_rgba(56,189,248,0.55)]' : ''} ${className ?? ''}`}
        style={{
          width: size,
          height: size,
          // The shipped artwork sits on a black plate — drop it out so the
          // mark floats over glass panels and the blueprint background.
          mixBlendMode: 'lighten',
        }}
      />
    )
  }

  return (
    <PlaceholderMark size={size} className={className} glow={glow} />
  )
}

/** Temporary emblem used until the real logo file is added. */
function PlaceholderMark({
  size,
  className,
  glow,
}: {
  size: number
  className?: string
  glow: boolean
}) {
  const id = 'luxion-mark'
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role="img"
      aria-label="Luxion"
      className={`shrink-0 ${glow ? 'drop-shadow-[0_0_12px_rgba(56,189,248,0.6)]' : ''} ${className ?? ''}`}
    >
      <defs>
        <radialGradient id={`${id}-core`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="45%" stopColor="#bae6fd" />
          <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.15" />
        </radialGradient>
        <linearGradient id={`${id}-ring`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7dd3fc" />
          <stop offset="100%" stopColor="#2563eb" />
        </linearGradient>
      </defs>

      {/* concentric technical rings */}
      <circle cx="50" cy="50" r="46" fill="none" stroke={`url(#${id}-ring)`} strokeWidth="3.5" />
      <circle cx="50" cy="50" r="38" fill="none" stroke={`url(#${id}-ring)`} strokeWidth="3" />
      <circle
        cx="50"
        cy="50"
        r="31"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="2.5"
        strokeDasharray="10 7"
        opacity="0.85"
      />

      {/* compass star */}
      <path
        d="M50 22 L57 43 L78 50 L57 57 L50 78 L43 57 L22 50 L43 43 Z"
        fill="none"
        stroke="#7dd3fc"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <path
        d="M50 34 L54.5 45.5 L66 50 L54.5 54.5 L50 66 L45.5 54.5 L34 50 L45.5 45.5 Z"
        fill={`url(#${id}-core)`}
        opacity="0.95"
      />

      {/* centre core */}
      <circle cx="50" cy="50" r="9" fill={`url(#${id}-core)`} />
      <circle cx="50" cy="50" r="4.5" fill="#ffffff" />
    </svg>
  )
}
