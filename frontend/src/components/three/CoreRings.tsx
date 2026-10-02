import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'

/** Radial tick marks — the drafting/registration language of the blueprint. */
function makeTicks(count: number, radius: number, length: number): THREE.BufferGeometry {
  const positions = new Float32Array(count * 6)
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    const reach = i % 5 === 0 ? length : length * 0.4
    const offset = i * 6
    positions[offset] = cos * radius
    positions[offset + 1] = sin * radius
    positions[offset + 2] = 0
    positions[offset + 3] = cos * (radius + reach)
    positions[offset + 4] = sin * (radius + reach)
    positions[offset + 5] = 0
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  return geometry
}

/**
 * Layer 5 — orbital rings, blueprint tick rings, segmented outer arcs and
 * sensor nodes. Rings expand slightly on a pulse.
 */
export function CoreRings({ ringCount, detail }: { ringCount: number; detail: boolean }) {
  const drive = useDrive()
  const spinRefs = useRef<THREE.Group[]>([])
  const blueprintsRef = useRef<THREE.Group>(null)
  const nodesRef = useRef<THREE.InstancedMesh>(null)
  const nodesGroupRef = useRef<THREE.Group>(null)

  const rings = useMemo(
    () =>
      Array.from({ length: ringCount }, (_, i) => ({
        radius: 1.42 + i * 0.23,
        tube: 0.004 + (i % 3) * 0.002,
        tiltX: ((i % 3) - 1) * 0.55,
        tiltZ: (((i * 7) % 5) - 2) * 0.28,
        speed: (i % 2 === 0 ? 1 : -1) * (0.1 + i * 0.045),
        arc: i % 3 === 1 ? Math.PI * 1.4 : Math.PI * 2,
      })),
    [ringCount],
  )

  const tickGeometries = useMemo(() => {
    if (!detail) return []
    return [
      makeTicks(72, 1.58, 0.12),
      makeTicks(48, 2.28, 0.16),
      makeTicks(96, 2.72, 0.07),
    ]
  }, [detail])

  const tickMaterial = useMemo(
    () =>
      new THREE.LineBasicMaterial({
        color: '#7dd3fc',
        transparent: true,
        opacity: 0.32,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    [],
  )

  const nodeMaterial = useMemo(
    () => new THREE.MeshBasicMaterial({ color: '#bae6fd', toneMapped: false }),
    [],
  )

  const nodesGeometry = useMemo(() => new THREE.SphereGeometry(0.028, 8, 8), [])

  useEffect(
    () => () => {
      tickGeometries.forEach((geometry) => geometry.dispose())
      tickMaterial.dispose()
      nodeMaterial.dispose()
      nodesGeometry.dispose()
    },
    [tickGeometries, tickMaterial, nodeMaterial, nodesGeometry],
  )

  useEffect(() => {
    const mesh = nodesRef.current
    if (!mesh) return
    const dummy = new THREE.Object3D()
    const count = mesh.instanceMatrix.count
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2
      dummy.position.set(Math.cos(angle) * 2.06, Math.sin(angle) * 0.42, Math.sin(angle) * 2.06)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    }
    mesh.instanceMatrix.needsUpdate = true
  }, [])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1)
    const breathe = 1 + drive.expand * 0.14 + drive.energy * 0.02

    spinRefs.current.forEach((group) => {
      if (!group) return
      group.rotation.y +=
        dt * (group.userData.speed ?? 0.1) * (0.5 + drive.ringSpeed) * drive.motion
      group.scale.setScalar(breathe)
    })

    if (blueprintsRef.current) {
      blueprintsRef.current.rotation.z -= dt * 0.035 * (0.5 + drive.ringSpeed) * drive.motion
      blueprintsRef.current.scale.setScalar(1 + drive.expand * 0.06)
    }

    tickMaterial.color.copy(drive.color)
    tickMaterial.opacity = 0.22 + drive.energy * 0.3
    nodeMaterial.color.copy(drive.color)

    if (nodesGroupRef.current) {
      nodesGroupRef.current.rotation.y += dt * 0.22 * (0.5 + drive.ringSpeed) * drive.motion
      nodesGroupRef.current.scale.setScalar(1 + drive.expand * 0.1)
    }
  })

  return (
    <group>
      {rings.map((ring, index) => (
        <group
          key={index}
          ref={(node) => {
            if (node) {
              node.userData.speed = ring.speed
              spinRefs.current[index] = node
            }
          }}
        >
          <mesh rotation={[ring.tiltX, 0, ring.tiltZ]}>
            <torusGeometry args={[ring.radius, ring.tube, 3, 160, ring.arc]} />
            <meshBasicMaterial
              color="#7dd3fc"
              transparent
              opacity={0.42}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </group>
      ))}

      {/* blueprint rings facing the camera */}
      <group ref={blueprintsRef}>
        <mesh>
          <torusGeometry args={[1.5, 0.003, 3, 128]} />
          <meshBasicMaterial
            color="#38bdf8"
            transparent
            opacity={0.45}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        <mesh rotation-z={0.4}>
          <torusGeometry args={[2.62, 0.003, 3, 128]} />
          <meshBasicMaterial
            color="#38bdf8"
            transparent
            opacity={0.3}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        {tickGeometries.map((geometry, index) => (
          <lineSegments key={index} geometry={geometry} material={tickMaterial} />
        ))}
      </group>

      {/* sensor nodes orbiting in a shallow ellipse */}
      <group ref={nodesGroupRef} rotation={[0.32, 0, 0.18]}>
        <instancedMesh
          ref={nodesRef}
          args={[nodesGeometry, nodeMaterial, 14]}
          frustumCulled={false}
        />
      </group>
    </group>
  )
}
