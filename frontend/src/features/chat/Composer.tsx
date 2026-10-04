import { useEffect, useRef } from 'react'
import { MicIcon, MicOffIcon, SendIcon, StopIcon } from '../../components/icons'

/** Push-to-talk + live (wake-word) listening controls shown in the composer. */
export interface ComposerVoice {
  /** `recognize()` is blocking on one utterance. */
  pttBusy: boolean
  onPtt: () => void
  /** The continuous wake-word session is open. */
  live: boolean
  onToggleLive: () => void
  /** Status / error line shown under the composer. */
  hint: string | null
  /** Capability refused or the backend is offline — buttons stay inert. */
  disabled: boolean
}

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  busy: boolean
  disabled?: boolean
  voice?: ComposerVoice
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  disabled,
  voice,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [value])

  const canSend = !busy && !disabled && value.trim().length > 0
  const pttBlocked = voice == null || voice.disabled || voice.pttBusy || voice.live

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

        {voice ? (
          <>
            <button
              type="button"
              onClick={voice.onPtt}
              disabled={pttBlocked}
              aria-label="Push to talk"
              title={
                voice.live
                  ? 'Turn off live listening to use push-to-talk'
                  : 'Push to talk — say one sentence and the text lands in the box'
              }
              className={`flex size-10 shrink-0 items-center justify-center rounded-lg border transition duration-200 ${
                voice.pttBusy
                  ? 'border-danger/50 bg-danger/10 text-danger'
                  : pttBlocked
                    ? 'cursor-not-allowed border-white/10 text-muted/40'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
              }`}
            >
              <MicIcon className={`size-4 ${voice.pttBusy ? 'animate-pulse' : ''}`} />
            </button>
            <button
              type="button"
              onClick={voice.onToggleLive}
              disabled={voice.disabled}
              aria-label="Live listening (wake word)"
              aria-pressed={voice.live}
              title={
                voice.live
                  ? 'Live listening is on — tap to turn it off'
                  : 'Live listening — say the wake phrase to talk to Luxion'
              }
              className={`flex size-10 shrink-0 items-center justify-center rounded-lg border transition duration-200 ${
                voice.disabled
                  ? 'cursor-not-allowed border-white/10 text-muted/40'
                  : voice.live
                    ? 'cursor-pointer border-tint/60 bg-tint/12 text-tint shadow-[0_0_14px_-4px] shadow-tint/60'
                    : 'cursor-pointer border-white/15 text-muted hover:border-tint/60 hover:text-ink'
              }`}
            >
              {voice.live ? <MicIcon className="size-4" /> : <MicOffIcon className="size-4" />}
            </button>
          </>
        ) : null}

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="flex size-10 items-center justify-center rounded-lg border border-warning/40 text-warning transition duration-200 hover:bg-warning/10"
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
      <p
        className={`mt-2 px-1 text-[11px] ${
          voice?.hint ? 'text-tint' : 'text-muted/70'
        }`}
      >
        {voice?.hint ??
          'Responses stream from your configured model. History stays on this machine.'}
      </p>
    </div>
  )
}
