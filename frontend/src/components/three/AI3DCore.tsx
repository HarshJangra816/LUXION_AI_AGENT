import { Canvas, useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

import { useAIState } from '../../lib/aiState'
import { useGraphics } from '../../lib/graphics'
import { CoreController, CoreDriveProvider, useDrive } from './coreDrive'
import { CoreCore } from './CoreCore'
import { CoreField } from './CoreField'
import { CoreHUD } from './CoreHUD'
import { CoreParticles } from './CoreParticles'
import { CoreRings } from './CoreRings'
import { CoreShell } from './CoreShell'
import { CoreWireframe } from './CoreWireframe'

/** Very slow orbital drift — atmospheric, never nauseating. */
function CameraRig({ orbit }: { orbit: boolean }) {
  useFrame((state, rawDt) => {
    const dt = Math.min(rawDt, 0.1)
    const time = state.clock.elapsedTime
    const targetX = orbit ? Math.sin(time * 0.06) * 0.32 : 0
    const targetY = orbit ? Math.cos(time * 0.045) * 0.18 : 0

    state.camera.position.x = THREE.MathUtils.damp(state.camera.position.x, targetX, 1.5, dt)
    state.camera.position.y = THREE.MathUtils.damp(state.camera.position.y, targetY, 1.5, dt)
    state.camera.position.z = 6.6
    state.camera.lookAt(0, 0, 0)
  })

  return null
}

function Scene({ orbit }: { orbit: boolean }) {
  const { profile } = useGraphics()
  const drive = useDrive()
  const groupRef = useRef<THREE.Group>(null)

  useFrame(() => {
    const group = groupRef.current
    if (!group) return
    group.position.x = 0.15 + drive.parallaxX * 2.2
    group.position.y = 0.5 + drive.parallaxY * 2.2
  })

  return (
    <>
      <ambientLight intensity={0.45} color="#1e3a5f" />
      <directionalLight position={[5, 6, 4]} intensity={1.1} color="#7dd3fc" />
      <directionalLight position={[-6, -3, -4]} intensity={0.5} color="#1d4ed8" />

      <CameraRig orbit={orbit} />

      <group ref={groupRef} position={[0.15, 0.5, 0]}>
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

/**
 * The blueprint AI core: real-time WebGL layered behind the glass UI.
 * Layer order — core → transparent sphere → wireframe → mechanical shell →
 * orbital rings → particles → outer energy field.
 */
export function AI3DCore({ showHud = false }: { showHud?: boolean }) {  const { profile, reducedMotion, brightness } = useGraphics()
  const { fireClickPulse, state } = useAIState()

  return (
    <CoreDriveProvider>
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{ opacity: brightness }}
      >
        <Canvas
          dpr={profile.dpr}
          gl={{
            antialias: profile.antialias,
            alpha: true,
            powerPreference: 'high-performance',
          }}
          camera={{ position: [0, 0, 6.6], fov: 42, near: 0.1, far: 60 }}
        >
          <CoreController>
            <Scene orbit={!reducedMotion} />
          </CoreController>
        </Canvas>
      </div>

      {showHud ? (
        <div className="pointer-events-none fixed inset-0 z-20">
          {/* Invisible, keyboard-reachable target over the core itself. Kept
              smaller than the core band so it can never swallow clicks from
              the content that scrolls below it. */}
          <button
            type="button"
            onClick={fireClickPulse}
            aria-label="Pulse the Luxion core"
            className="pointer-events-auto absolute top-[40%] left-[53.7%] size-[clamp(130px,17vw,210px)] -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full border border-transparent transition duration-300 hover:border-tint/35 hover:bg-tint/5 focus-visible:border-tint/70 focus-visible:outline-none"
            style={{
              background:
                state === 'error'
                  ? 'radial-gradient(circle, rgba(244,63,94,0.06) 0%, transparent 70%)'
                  : state === 'warning'
                    ? 'radial-gradient(circle, rgba(245,158,11,0.06) 0%, transparent 70%)'
                    : 'radial-gradient(circle, rgba(56,189,248,0.05) 0%, transparent 70%)',
            }}
          />

          <CoreHUD />
        </div>
      ) : null}
    </CoreDriveProvider>
  )
}

/** Default export so the whole three.js layer can be code-split. */
export default AI3DCore
