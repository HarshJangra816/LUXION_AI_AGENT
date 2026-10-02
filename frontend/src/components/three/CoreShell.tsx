import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'

const SHELL_RADIUS = 0.16
const BANDS = [-0.78, -0.3, 0.3, 0.78]

/**
 * Layer 4 — mechanical segmented geometry: latitude bands built from
 * arc segments with real gaps, lit from inside by the core.
 */
export function CoreShell({ segments }: { segments: number }) {
  const drive = useDrive()
  const groupRefs = useRef<THREE.Group[]>([])

  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#0d2438',
        emissive: new THREE.Color('#38bdf8'),
        emissiveIntensity: 0.5,
        metalness: 0.75,
        roughness: 0.32,
        transparent: true,
        opacity: 0.92,
      }),
    [],
  )

  const bands = useMemo(() => {
    const count = Math.max(3, segments)
    const step = (Math.PI * 2) / count
    const arc = step * 0.58
    return BANDS.map((latitude, bandIndex) => ({
      key: bandIndex,
      latitude,
      radius: SHELL_RADIUS * Math.cos(latitude),
      y: SHELL_RADIUS * Math.sin(latitude),
      step,
      arc,
      count,
      speed: [0.08, -0.12, 0.1, -0.07][bandIndex],
      tube: bandIndex === 1 || bandIndex === 2 ? 0.022 : 0.016,
    }))
  }, [segments])

  useEffect(() => () => material.dispose(), [material])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1)
    material.emissive.copy(drive.color)
    material.emissiveIntensity = 0.35 + drive.energy * 0.9 + drive.pulse * 0.8
    groupRefs.current.forEach((group) => {
      if (group)       group.rotation.y += dt * group.userData.speed * (0.4 + drive.speed) * drive.motion
    })
  })

  return (
    <group>
      {bands.map((band, bandIndex) => (
        <group
          key={band.key}
          ref={(node) => {
            if (node) {
              node.userData.speed = band.speed
              groupRefs.current[bandIndex] = node
            }
          }}
        >
          {Array.from({ length: band.count }, (_, index) => (
            <group key={index} rotation-y={index * band.step}>
              <mesh position={[0, band.y, 0]} rotation={[-Math.PI / 2, 0, 0]} material={material}>
                <torusGeometry args={[band.radius, band.tube, 4, 28, band.arc]} />
              </mesh>
            </group>
          ))}
          {/* coupling blocks sitting in the gaps between segments */}
          {Array.from({ length: band.count }, (_, index) => (
            <group key={`clamp-${index}`} rotation-y={index * band.step + band.step * 0.79}>
              <mesh position={[band.radius, band.y, 0]} material={material}>
                <boxGeometry args={[0.05, 0.05, 0.11]} />
              </mesh>
            </group>
          ))}
        </group>
      ))}

      {/* equatorial seam */}
      <mesh material={material} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[SHELL_RADIUS, 0.008, 3, 96]} />
      </mesh>
    </group>
  )
}
