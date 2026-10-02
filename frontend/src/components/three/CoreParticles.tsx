import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uSpeed;
  uniform float uEnergy;
  attribute float aRadius;
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aIncline;
  attribute float aSize;
  varying float vAlpha;

  void main() {
    float angle = aPhase + uTime * aSpeed * (0.4 + uSpeed * 1.6);
    vec3 p = vec3(cos(angle) * aRadius, 0.0, sin(angle) * aRadius);

    float c = cos(aIncline);
    float s = sin(aIncline);
    p = vec3(p.x, p.y * c - p.z * s, p.y * s + p.z * c);

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = aSize * (215.0 / -mv.z) * (0.55 + uEnergy * 0.7);
    vAlpha = 0.16 + 0.4 * uEnergy;
    gl_Position = projectionMatrix * mv;
  }
`

const fragmentShader = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float alpha = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(uColor, alpha * vAlpha);
  }
`

/** Deterministic PRNG so a quality switch rebuilds the same field. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Layer 6 — orbital particle streams, driven entirely on the GPU. */
export function CoreParticles({ count }: { count: number }) {
  const drive = useDrive()

  const geometry = useMemo(() => {
    const random = mulberry32(0x1f5a ^ count)
    const positions = new Float32Array(count * 3)
    const radius = new Float32Array(count)
    const phase = new Float32Array(count)
    const speed = new Float32Array(count)
    const incline = new Float32Array(count)
    const size = new Float32Array(count)

    for (let i = 0; i < count; i++) {
      radius[i] = 1.35 + random() * 1.85
      phase[i] = random() * Math.PI * 2
      speed[i] = 0.15 + random() * 0.75
      incline[i] = (random() - 0.5) * 2.4
      size[i] = 0.6 + random() * 2.4
    }

    const buffer = new THREE.BufferGeometry()
    buffer.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    buffer.setAttribute('aRadius', new THREE.BufferAttribute(radius, 1))
    buffer.setAttribute('aPhase', new THREE.BufferAttribute(phase, 1))
    buffer.setAttribute('aSpeed', new THREE.BufferAttribute(speed, 1))
    buffer.setAttribute('aIncline', new THREE.BufferAttribute(incline, 1))
    buffer.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
    return buffer
  }, [count])

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        uniforms: {
          uTime: { value: 0 },
          uSpeed: { value: 0.2 },
          uEnergy: { value: 0.3 },
          uColor: { value: new THREE.Color('#7dd3fc') },
        },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [],
  )

  useEffect(
    () => () => {
      geometry.dispose()
      material.dispose()
    },
    [geometry, material],
  )

  useFrame(() => {
    const u = material.uniforms
    u.uTime.value = drive.time
    u.uSpeed.value = drive.speed
    u.uEnergy.value = drive.energy
    u.uColor.value.copy(drive.color)
  })

  return <points geometry={geometry} material={material} frustumCulled={false} />
}
