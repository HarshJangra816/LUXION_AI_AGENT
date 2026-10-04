/** Inline SVG icons (design system forbids emoji as icons). */

type IconProps = { className?: string }

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

export function PlusIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function TrashIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M4 7h16M10 11v6M14 11v6" />
      <path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  )
}

export function SendIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M4.5 12L20 4l-4.5 16-4-6.5L4.5 12z" />
      <path d="M11.5 13.5L20 4" />
    </svg>
  )
}

export function StopIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden className={className}>
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </svg>
  )
}

export function ChatIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M20 12a7 7 0 0 1-7 7H8l-4 3v-4.5A7 7 0 0 1 8 5h5a7 7 0 0 1 7 7z" />
    </svg>
  )
}

export function RefreshIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M20 11a8 8 0 1 0-.7 4.5" />
      <path d="M20 5v6h-6" />
    </svg>
  )
}

export function AlertIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 4.5L21 19H3l9-14.5z" />
      <path d="M12 10v4M12 17h.01" />
    </svg>
  )
}

export function ArrowIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

export function GaugeIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 14l4-4" />
      <path d="M4.5 18a9 9 0 1 1 15 0" />
      <circle cx="12" cy="14" r="1.4" />
    </svg>
  )
}

export function TypeIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M4 7V5h16v2" />
      <path d="M12 5v14" />
      <path d="M9 19h6" />
    </svg>
  )
}

export function PaletteIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3a9 9 0 1 0 0 18c1.2 0 2-.9 2-2 0-.6-.3-1-.7-1.4-.4-.4-.6-.8-.6-1.3 0-1 .8-1.8 1.8-1.8H16a5 5 0 0 0 5-5c0-3.9-4-6.5-9-6.5z" />
      <circle cx="7.5" cy="12.5" r="1" />
      <circle cx="10.5" cy="8" r="1" />
      <circle cx="15" cy="8.5" r="1" />
    </svg>
  )
}

/** Terminal prompt — tool execution chips. */
export function TerminalIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
      <path d="M7.5 9.5L10.5 12l-3 2.5M13 15h4" />
    </svg>
  )
}

/** Shield — permission prompts. */
export function ShieldIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3.5l7 2.8v5.4c0 3.9-2.9 6.6-7 8.8-4.1-2.2-7-4.9-7-8.8V6.3l7-2.8z" />
      <path d="M9.5 12l1.8 1.8L15 10" />
    </svg>
  )
}

export function CheckIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  )
}

export function XIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
    </svg>
  )
}

/** Microphone — push-to-talk and live listening (Phase 4). */
export function MicIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3.5a2.6 2.6 0 0 1 2.6 2.6v5.2a2.6 2.6 0 0 1-5.2 0V6.1A2.6 2.6 0 0 1 12 3.5z" />
      <path d="M6.6 11.2a5.4 5.4 0 0 0 10.8 0" />
      <path d="M12 16.6V20" />
      <path d="M9 20h6" />
    </svg>
  )
}

/** Microphone muted — live listening is off. */
export function MicOffIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3.5a2.6 2.6 0 0 1 2.6 2.6v3.1" />
      <path d="M9.4 8.1v3.2a2.6 2.6 0 0 0 4.3 2" />
      <path d="M6.6 11.2a5.4 5.4 0 0 0 8.4 4.5" />
      <path d="M17.4 11.2c0 .6-.07 1.2-.2 1.7" />
      <path d="M12 16.6V20" />
      <path d="M4 4l16 16" />
    </svg>
  )
}

