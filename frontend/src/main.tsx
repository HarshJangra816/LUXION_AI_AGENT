import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/fira-sans/latin-300.css'
import '@fontsource/fira-sans/latin-400.css'
import '@fontsource/fira-sans/latin-500.css'
import '@fontsource/fira-sans/latin-600.css'
import '@fontsource/fira-sans/latin-700.css'
import '@fontsource/fira-code/latin-400.css'
import '@fontsource/fira-code/latin-500.css'
import '@fontsource/fira-code/latin-600.css'
import './index.css'
import App from './App.tsx'
import { AppearanceProvider } from './lib/appearance'
import { AIStateProvider } from './lib/aiState'
import { GraphicsProvider } from './lib/graphics'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GraphicsProvider>
      <AppearanceProvider>
        <AIStateProvider>
          <App />
        </AIStateProvider>
      </AppearanceProvider>
    </GraphicsProvider>
  </StrictMode>,
)
