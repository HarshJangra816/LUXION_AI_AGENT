import { useCallback, useEffect, useState } from 'react'
import { getCapabilities, type CapabilityReport } from '../../lib/capabilities'
import { BrowserCard } from '../settings/BrowserCard'
import { CodeCard } from '../settings/CodeCard'
import { DesktopCard } from '../settings/DesktopCard'
import { EmailCard } from '../settings/EmailCard'
import { NotifyCard } from '../settings/NotifyCard'
import { VoiceCard } from '../settings/VoiceCard'
import { WebCard } from '../settings/WebCard'
import { WhatsAppCard } from '../settings/WhatsAppCard'

/**
 * Everything Luxion can drive outside itself: voice, communication (email,
 * WhatsApp, notifications), browser, desktop, coding and web intelligence.
 * Each card is self-contained (own fetch + save) and collapsible; Voice needs
 * the capabilities report for its mic/speaker gates, which is loaded once
 * here.
 */
export function IntegrationsPage() {
  const [caps, setCaps] = useState<CapabilityReport | null>(null)

  const loadCaps = useCallback(async (signal?: AbortSignal) => {
    try {
      setCaps(await getCapabilities(signal))
    } catch {
      // VoiceCard degrades gracefully without the report (server state only)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    void loadCaps(controller.signal)
    return () => controller.abort()
  }, [loadCaps])

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6 md:p-8">
      <VoiceCard caps={caps} />
      <EmailCard />
      <WhatsAppCard />
      <NotifyCard />
      <BrowserCard />
      <DesktopCard />
      <CodeCard />
      <WebCard />
    </div>
  )
}
