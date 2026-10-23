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

/** Down chevron — rotated by callers to mark collapse/expand state. */
export function ChevronIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M6 9.5l6 6 6-6" />
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

/** Globe - browser agent (Settings → Browser). */
export function GlobeIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z" />
    </svg>
  )
}

/** Eye - computer vision (Settings → Vision). */
export function EyeIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

/** Camera - webcam capture (Settings → Vision). */
export function CameraIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M3 8.5A2 2 0 0 1 5 6.5h2.2l1.3-2h7l1.3 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  )
}

/** Fingerprint - biometric authentication (Settings → Auth). */
export function FingerprintIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 10.5a2.5 2.5 0 0 1 2.5 2.5c0 2.2-.4 4.2-1.1 6" />
      <path d="M8.8 20.4A13 13 0 0 0 9.5 13a2.5 2.5 0 0 1 5 0c0 1.4-.1 2.8-.4 4.1" />
      <path d="M5.6 18.6A11.6 11.6 0 0 0 7 13a5 5 0 0 1 10 0c0 1.6-.1 3.1-.4 4.5" />
      <path d="M4.1 14.6a8 8 0 0 1 1.4-3.3" />
    </svg>
  )
}

/** Desktop monitor + pointer - computer automation (Settings → Desktop). */
export function DesktopIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <rect x="2.5" y="4" width="19" height="12.5" rx="2" />
      <path d="M9 20.5h6M12 16.5v4" />
      <path d="M13 8.5l3.6 3.6-1.5.4.9 2-1.3.6-.9-2-1.2 1.2z" />
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

/** Shield with a check — voice/face second factor (Phase 11c). */
export function ShieldCheckIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3.5l7 2.8v5.4c0 3.9-2.9 6.6-7 8.8-4.1-2.2-7-4.9-7-8.8V6.3l7-2.8z" />
      <path d="M9.2 12.2l1.9 1.9 3.7-3.9" />
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

/** Envelope — email integration. */
export function MailIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="M3.5 7l8.5 6 8.5-6" />
    </svg>
  )
}

/** Phone handset — WhatsApp / phone messaging. */
export function PhoneIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M7 3.5h10a1.5 1.5 0 0 1 1.5 1.5v14a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z" />
      <path d="M10 17.2h4" />
    </svg>
  )
}

/** Bell — desktop notifications. */
export function BellIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2h-14l1.5-2z" />
      <path d="M10.2 20.5a2 2 0 0 0 3.6 0" />
      <path d="M12 5.5V3.8" />
    </svg>
  )
}

