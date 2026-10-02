import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'
import { glowTexture, haloTexture } from './textures'

const fieldVertex = /* glsl */ `
  varying vec3 vNormalV;
  varying vec3 vView;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vNormalV = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`

const fieldFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uEnergy;
  varying vec3 vNormalV;
  varying vec3 vView;

  void main() {
    float fres = pow(1.0 - abs(dot(normalize(vNormalV), normalize(vView))), 3.0);
    gl_FragColor = vec4(uColor, fres * (0.1 + uEnergy * 0.16));
  }
`

/** Layer 7 — the outer energy field and its soft atmospheric halo. */
export function CoreField() {
  const drive = useDrive()

  const fieldMaterial = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: fieldVertex,
        fragmentShader: fieldFragment,
        uniforms: {
          uColor: { value: new THREE.Color('#38bdf8') },
          uEnergy: { value: 0.3 },
        },
        transparent: true,
        depthWrite: false,
        side: THREE.BackSide,
        blending: THREE.AdditiveBlending,
      }),
    [],
  )

  const haloMaterial = useMemo(
    () =>
      new THREE.SpriteMaterial({
        map: haloTexture(),
        color: '#7dd3fc',
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      }),
    [],
  )

  const glowMaterial = useMemo(
    () =>
      new THREE.SpriteMaterial({
        map: glowTexture(),
        color: '#0ea5e9',
        transparent: true,
        opacity: 0.22,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [],
  )

  useEffect(
    () => () => {
      fieldMaterial.dispose()
      haloMaterial.dispose()
      glowMaterial.dispose()
    },
    [fieldMaterial, haloMaterial, glowMaterial],
  )

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1)
    fieldMaterial.uniforms.uEnergy.value = drive.energy
    fieldMaterial.uniforms.uColor.value.copy(drive.color)

    haloMaterial.color.copy(drive.color)
    haloMaterial.opacity = 0.07 + drive.energy * 0.1
    haloMaterial.rotation -= dt * 0.05 * (0.4 + drive.ringSpeed) * drive.motion

    glowMaterial.color.copy(drive.color)
    glowMaterial.opacity = 0.1 + drive.energy * 0.1
  })

  return (
    <group>
      <mesh material={fieldMaterial}>
        <sphereGeometry args={[3.4, 32, 24]} />
      </mesh>
      <sprite scale={[6, 6, 1]} material={haloMaterial} />
      <sprite scale={[6.5, 6.5, 1]} material={glowMaterial} />
    </group>
  )
}
