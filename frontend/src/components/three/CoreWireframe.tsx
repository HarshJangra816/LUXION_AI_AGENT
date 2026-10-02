import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

import { useDrive } from './coreDrive'

const shellVertex = /* glsl */ `
  varying vec3 vNormalV;
  varying vec3 vView;
  varying vec3 vPos;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vNormalV = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    vPos = position;
    gl_Position = projectionMatrix * mv;
  }
`

const shellFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uEnergy;
  uniform float uTime;
  varying vec3 vNormalV;
  varying vec3 vView;
  varying vec3 vPos;

  void main() {
    float fres = pow(1.0 - abs(dot(normalize(vNormalV), normalize(vView))), 2.2);
    float latitude = smoothstep(0.44, 0.5, abs(fract(vPos.y * 5.0 + uTime * 0.05) - 0.5) * 2.0);
    float alpha = fres * (0.18 + uEnergy * 0.2) + latitude * 0.04;
    gl_FragColor = vec4(uColor * (0.65 + uEnergy * 0.5), alpha);
  }
`

/**
 * Layers 2 + 3 — the transparent geometric sphere and the technical
 * wireframe that sells the "engineering drawing" look.
 */
export function CoreWireframe({ segments }: { segments: number }) {
  const drive = useDrive()
  const shellRef = useRef<THREE.Group>(null)
  const wireRef = useRef<THREE.Group>(null)

  const shellMaterial = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: shellVertex,
        fragmentShader: shellFragment,
        uniforms: {
          uColor: { value: new THREE.Color('#7dd3fc') },
          uEnergy: { value: 0.3 },
          uTime: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
      }),
    [],
  )

  const wireGeometry = useMemo(() => {
    const source = new THREE.IcosahedronGeometry(1.06, Math.max(1, Math.min(2, segments)))
    const wire = new THREE.WireframeGeometry(source)
    source.dispose()
    return wire
  }, [segments])

  const shellWireGeometry = useMemo(() => {
    const source = new THREE.IcosahedronGeometry(1.24, 0)
    const wire = new THREE.WireframeGeometry(source)
    source.dispose()
    return wire
  }, [])

  const wireMaterial = useMemo(
    () =>
      new THREE.LineBasicMaterial({
        color: '#7dd3fc',
        transparent: true,
        opacity: 0.3,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    [],
  )

  const shellWireMaterial = useMemo(
    () =>
      new THREE.LineBasicMaterial({
        color: '#38bdf8',
        transparent: true,
        opacity: 0.12,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    [],
  )

  useEffect(
    () => () => {
      shellMaterial.dispose()
      wireGeometry.dispose()
      shellWireGeometry.dispose()
      wireMaterial.dispose()
      shellWireMaterial.dispose()
    },
    [shellMaterial, wireGeometry, shellWireGeometry, wireMaterial, shellWireMaterial],
  )

  useFrame((_, dt) => {
    const step = Math.min(dt, 0.1)
    shellMaterial.uniforms.uTime.value += step * (0.5 + drive.speed * 0.6) * drive.motion
    shellMaterial.uniforms.uEnergy.value = drive.energy
    shellMaterial.uniforms.uColor.value.copy(drive.color)

    wireMaterial.color.copy(drive.color)
    wireMaterial.opacity = 0.2 + drive.energy * 0.3
    shellWireMaterial.color.copy(drive.color)

    if (shellRef.current) {
      shellRef.current.rotation.y += step * 0.06 * drive.speed
      shellRef.current.rotation.x = Math.sin(drive.time * 0.3) * 0.08
    }
    if (wireRef.current) {
      wireRef.current.rotation.y -= step * 0.12 * drive.speed
      wireRef.current.rotation.z += step * 0.05 * drive.speed
    }
  })

  return (
    <group>
      <mesh material={shellMaterial}>
        <sphereGeometry args={[0.95, 48, 32]} />
      </mesh>

      <group ref={shellRef}>
        <lineSegments geometry={shellWireGeometry} material={shellWireMaterial} />
      </group>

      <group ref={wireRef}>
        <lineSegments geometry={wireGeometry} material={wireMaterial} />
      </group>
    </group>
  )
}
