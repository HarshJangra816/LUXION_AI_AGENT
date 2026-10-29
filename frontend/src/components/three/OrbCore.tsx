/**
 * The floating orb window's core (PRD §29 "Desktop Orb", Phase 12b).
 *
 * A second, always-on-top, transparent, frameless webview that shows the *same*
 * eleven PRD §30 states as the in-app core. It reuses every frozen `Core*`
 * primitive and the shared `CoreController`/`CoreDrive` machinery unchanged —
 * only the composition is new: centred, scaled to fit the window at any size,
 * with no HUD.
 *
 * Interaction split (PRD §29 "draggable" + "click interaction"):
 *
 * - The transparent **margin** around the core is the drag region — grabbing it
 *   moves the window.
 * - The **core** is the click target — pressing it flips the wake-word session
 *   open/closed (via the shared `flipVoiceListening`). Its resulting LISTENING
 *   frame reaches this window through the `AIStateMirrorProvider`, so state
 *   stays owned by the main window and is never driven twice.
 */

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'

import { useAIState } from '../../lib/aiState'
import { useGraphics } from '../../lib/graphics'
import { flipVoiceListening, getVoiceStatus } from '../../lib/voice'
import { CoreController, CoreDriveProvider, useDrive } from './coreDrive'
import { CoreCore } from './CoreCore'
import { CoreField } from './CoreField'
import { CoreParticles } from './CoreParticles'
import { CoreRings } from './CoreRings'
import { CoreShell } from './CoreShell'
import { CoreWireframe } from './CoreWireframe'

/** Rough outer radius of the composed core (sphere + rings + field). */
const ORB_RADIUS = 3.5
/** Fraction of the window's smaller axis the core should fill. */
const FILL = 0.76

/**
 * Back the camera off so the core always fits, whatever the window is resized
 * to. Fills the *smaller* axis so the orb is never clipped on a wide or a tall
 * window — the user can drag the floating window to any shape.
 */
function FitCamera() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const width = useThree((s) => s.size.width)
  const height = useThree((s) => s.size.height)

  useEffect(() => {
    if (width < 1 || height < 1) return
    // Half the visible extent per unit of depth at this field of view.
    const halfPerUnit = Math.tan((camera.fov * Math.PI) / 360)
    const half = Math.min(halfPerUnit * (width / height), halfPerUnit)
    camera.position.set(0, 0, ORB_RADIUS / (half * FILL))
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
  }, [camera, width, height])

  return null
}

function Scene() {
  const { profile } = useGraphics()
  const drive = useDrive()
  const groupRef = useRef<THREE.Group>(null)

  // Centred, with only a whisper of parallax so it reads as alive (not the
  // in-app core's larger offset — here the orb IS the whole window).
  useFrame(() => {
    const group = groupRef.current
    if (!group) return
    group.position.x = drive.parallaxX * 0.6
    group.position.y = drive.parallaxY * 0.6
  })

  return (
    <>
      <ambientLight intensity={0.45} color="#1e3a5f" />
      <directionalLight position={[5, 6, 4]} intensity={1.1} color="#7dd3fc" />
      <directionalLight position={[-6, -3, -4]} intensity={0.5} color="#1d4ed8" />

      <FitCamera />

      <group ref={groupRef}>
        <CoreField />
        <CoreRings ringCount={profile.rings} detail={profile.detailRings} />
        <CoreParticles count={profile.particles} />
        <CoreWireframe segments={profile.shellSegments} />
        <CoreShell segments={profile.shellSegments} />
        <CoreCore glowLayers={profile.glowLayers} />
      </group>
    </>
  )
}

export function OrbCore() {
  const { profile, brightness } = useGraphics()
  const { fireClickPulse } = useAIState()
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // Seed the click affordance from the backend — the session may already have
  // been opened from Settings → Voice, and the button must not lie about it.
  useEffect(() => {
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect -- async load, no sync setState
    getVoiceStatus(controller.signal)
      .then((status) => setListening(status.listening))
      .catch(() => undefined) // voice optional: the click reports its own error
    return () => controller.abort()
  }, [])

  /** Flip the mic open/closed; state itself comes back via the mirror. */
  const handleClick = () => {
    fireClickPulse()
    if (busy) return
    setBusy(true)
    void flipVoiceListening()
      .then((status) => {
        setListening(status.listening)
        setNotice(null)
      })
      .catch((caught: unknown) => {
        setNotice(caught instanceof Error ? caught.message : String(caught))
      })
      .finally(() => setBusy(false))
  }

  const label = busy
    ? 'Opening the microphone'
    : listening
      ? 'Stop listening on the Luxion orb'
      : 'Start listening on the Luxion orb'

  return (
    <CoreDriveProvider>
      <div
        className="relative h-screen w-screen overflow-hidden"
        style={{ opacity: brightness }}
      >
        {/* Drag region: the transparent margin around the core. The click
            target below sits on top with pointer-events, so grabbing the edge
            moves the window while pressing the core talks (PRD §29). */}
        <div data-tauri-drag-region className="absolute inset-0" />

        <div className="pointer-events-none absolute inset-0">
          <Canvas
            dpr={profile.dpr}
            gl={{
              antialias: profile.antialias,
              alpha: true,
              powerPreference: 'high-performance',
            }}
            camera={{ position: [0, 0, 12], fov: 42, near: 0.1, far: 60 }}
          >
            <CoreController>
              <Scene />
            </CoreController>
          </Canvas>
        </div>

        {/* Invisible, keyboard-reachable target locked over the core itself. */}
        <button
          type="button"
          onClick={handleClick}
          aria-label={label}
          title={notice ?? 'Drag the edge to move · click to talk'}
          className={`pointer-events-auto absolute top-1/2 left-1/2 size-[58%] -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full border transition duration-300 focus-visible:outline-none ${
            listening ? 'border-tint/60' : 'border-transparent hover:border-tint/30'
          }`}
        />
      </div>
    </CoreDriveProvider>
  )
}
