/**
 * Depth layer 1–2: far gradient, blueprint grid, galaxy star field,
 * vignette, atmosphere. Sits behind the WebGL canvas; both are fixed and
 * content floats above.
 */
import { GalaxyField } from './GalaxyField'

export function AmbientBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* far background — deep atmospheric blue */}
      <div className="absolute inset-0 bg-[radial-gradient(1200px_800px_at_50%_-10%,#0b2545_0%,#061426_45%,#020a16_100%)]" />

      {/* engineering blueprint grid */}
      <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(56,189,248,0.07)_1px,transparent_1px),linear-gradient(to_bottom,rgba(56,189,248,0.07)_1px,transparent_1px)] [background-size:56px_56px]" />
      <div className="absolute inset-0 opacity-[0.18] [background-image:linear-gradient(to_right,rgba(125,211,252,0.09)_1px,transparent_1px),linear-gradient(to_bottom,rgba(125,211,252,0.09)_1px,transparent_1px)] [background-size:224px_224px]" />

      {/* galaxy: star dust, nebulae and a slow spiral around the core */}
      <GalaxyField />

      {/* registration marks in the corners (blueprint drafting style) */}
      <span className="absolute top-5 left-5 h-8 w-8 border-t border-l border-cyan-200/25" />
      <span className="absolute top-5 right-5 h-8 w-8 border-t border-r border-cyan-200/25" />
      <span className="absolute bottom-5 left-5 h-8 w-8 border-b border-l border-cyan-200/25" />
      <span className="absolute right-5 bottom-5 h-8 w-8 border-r border-b border-cyan-200/25" />

      {/* soft light sources */}
      <div className="absolute top-[-18%] left-1/2 h-[560px] w-[900px] -translate-x-1/2 rounded-full bg-cyan-500/10 blur-[140px]" />
      <div className="absolute right-[-10%] bottom-[-20%] h-[520px] w-[620px] rounded-full bg-blue-700/20 blur-[150px]" />

      {/* vignette — keeps edges dark so glass panels read clearly */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,transparent_0%,rgba(2,8,18,0.55)_62%,rgba(2,6,14,0.92)_100%)]" />
    </div>
  )
}
