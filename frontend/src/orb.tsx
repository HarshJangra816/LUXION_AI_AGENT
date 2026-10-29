/**
 * Entry point for the floating orb window (PRD §29, Phase 12b).
 *
 * A separate webview from the main app, so it gets its own tiny React root:
 * the frozen `Core*` visual machinery, the appearance/graphics providers (which
 * read their persisted config independently), and a *mirror* of the AI state —
 * never a second owner. `main.tsx` still drives the real state machine.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { OrbCore } from './components/three/OrbCore'
import { AIStateMirrorProvider } from './lib/aiState'
import { AppearanceProvider } from './lib/appearance'
import { GraphicsProvider } from './lib/graphics'
import './index.css'
import './orb.css'

createRoot(document.getElementById('orb-root')!).render(
  <StrictMode>
    <GraphicsProvider>
      <AppearanceProvider>
        <AIStateMirrorProvider>
          <OrbCore />
        </AIStateMirrorProvider>
      </AppearanceProvider>
    </GraphicsProvider>
  </StrictMode>,
)
