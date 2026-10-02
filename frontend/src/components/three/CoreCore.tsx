import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'
import { glowTexture } from './textures'

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uEnergy;
  varying vec3 vNormalV;
  varying vec3 vView;
  varying vec3 vPos;

  void main() {
    vec3 p = position;
    float ripple = sin(p.y * 9.0 + uTime * 2.2) * cos(p.x * 7.0 - uTime * 1.7);
    p += normal * ripple * (0.014 + uEnergy * 0.03);

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vNormalV = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    vPos = p;
    gl_Position = projectionMatrix * mv;
  }
`

const fragmentShader = /* glsl */ `
  uniform vec3 uColor;
  uniform float uEnergy;
  uniform float uTime;
  varying vec3 vNormalV;
  varying vec3 vView;
  varying vec3 vPos;

  void main() {
    float fres = pow(1.0 - max(dot(normalize(vNormalV), normalize(vView)), 0.0), 1.5);
    float bands = 0.5 + 0.5 * sin(vPos.y * 14.0 - uTime * 3.0);
    vec3 base = mix(vec3(0.92, 0.98, 1.0), uColor, 0.5);
    vec3 col = base * (0.5 + fres * 1.05 + bands * 0.1 * uEnergy);
    col += uColor * uEnergy * 0.3;
    gl_FragColor = vec4(col, 1.0);
  }
`

/** Layer 1 — the luminous energy core at the centre of the machine. */
export function CoreCore({ glowLayers }: { glowLayers: number }) {
  const drive = useDrive()
  const groupRef = useRef<THREE.Group>(null)
  const lightRef = useRef<THREE.PointLight>(null)

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        uniforms: {
          uTime: { value: 0 },
          uEnergy: { value: 0.3 },
          uColor: { value: new THREE.Color('#38bdf8') },
        },
      }),
    [],
  )

  const spriteMaterial = useMemo(() => {
    const map = glowTexture()
    return Array.from(
      { length: glowLayers },
      () =>
        new THREE.SpriteMaterial({
          map,
          color: '#7dd3fc',
          transparent: true,
          opacity: 0.3,
          depthWrite: false,
          depthTest: false,
          blending: THREE.AdditiveBlending,
        }),
    )
  }, [glowLayers])

  useEffect(
    () => () => {
      material.dispose()
      spriteMaterial.forEach((sprite) => sprite.dispose())
    },
    [material, spriteMaterial],
  )

  useFrame((_, dt) => {
    const u = material.uniforms
    u.uTime.value += Math.min(dt, 0.1) * (0.4 + drive.speed) * drive.motion
    u.uEnergy.value = drive.energy
    u.uColor.value.copy(drive.color)

    spriteMaterial.forEach((sprite, index) => {
      sprite.opacity = (0.32 - index * 0.08) * (0.4 + drive.energy * 0.6)
      sprite.color.copy(drive.color)
    })

    const scale = 1 + drive.pulse * 0.35 + drive.energy * 0.1
    groupRef.current?.scale.setScalar(scale)
    if (lightRef.current) {
      lightRef.current.intensity = 2.5 + drive.energy * 6 + drive.pulse * 6
      lightRef.current.color.copy(drive.color)
    }
  })

  const sizes = useMemo(() => Array.from({ length: glowLayers }, (_, i) => 1.7 + i * 1.15), [glowLayers])

  return (
    <group ref={groupRef}>
      <mesh material={material}>
        <sphereGeometry args={[0.42, 48, 32]} />
      </mesh>

      {sizes.map((size, index) => (
        <sprite key={index} scale={[size, size, 1]} material={spriteMaterial[index]} />
      ))}

      <pointLight ref={lightRef} color="#7dd3fc" intensity={4} distance={16} decay={2} />
    </group>
  )
}
