import { useEffect, useRef } from 'react'
import { SendIcon, StopIcon } from '../../components/icons'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  busy: boolean
  disabled?: boolean
}

export function Composer({ value, onChange, onSend, onStop, busy, disabled }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [value])

  const canSend = !busy && !disabled && value.trim().length > 0

  return (
    <div className="border-t border-white/10 bg-panel/85 p-4 backdrop-blur-xl md:px-6">
      <div className="flex items-end gap-3 rounded-xl border border-white/10 bg-panel-2/60 p-2 transition duration-200 focus-within:border-tint/70">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              if (canSend) onSend()
            }
          }}
          placeholder="Message Luxion…  (Enter to send, Shift+Enter for a new line)"
          className="max-h-44 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-sm text-ink placeholder:text-muted/70 focus:outline-none"
          aria-label="Message"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="flex size-10 cursor-pointer items-center justify-center rounded-lg border border-warning/40 text-warning transition duration-200 hover:bg-warning/10"
            aria-label="Stop generating"
            title="Stop generating"
          >
            <StopIcon className="size-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
            className={`flex size-10 items-center justify-center rounded-lg transition duration-200 ${
              canSend
                ? 'cursor-pointer bg-accent text-on-accent hover:brightness-110'
                : 'cursor-not-allowed bg-panel-2 text-muted/50'
            }`}
          >
            <SendIcon className="size-4" />
          </button>
        )}
      </div>
      <p className="mt-2 px-1 text-[11px] text-muted/70">
        Responses stream from your configured model. History stays on this machine.
      </p>
    </div>
  )
}
