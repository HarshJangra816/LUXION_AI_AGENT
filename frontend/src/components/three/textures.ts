import * as THREE from 'three'

let cached: THREE.Texture | null = null

/** Soft radial sprite used for every additive glow in the scene. */
export function glowTexture(): THREE.Texture {
  if (cached) return cached
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx) {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
    gradient.addColorStop(0, 'rgba(255,255,255,1)')
    gradient.addColorStop(0.18, 'rgba(186,230,253,0.85)')
    gradient.addColorStop(0.45, 'rgba(56,189,248,0.32)')
    gradient.addColorStop(1, 'rgba(14,165,233,0)')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, size, size)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  cached = texture
  return texture
}

/** Concentric halo texture — used for the outer energy field. */
let cachedHalo: THREE.Texture | null = null
export function haloTexture(): THREE.Texture {
  if (cachedHalo) return cachedHalo
  const size = 512
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.strokeStyle = 'rgba(125,211,252,0.55)'
    ctx.lineWidth = 2
    for (let i = 0; i < 5; i++) {
      const radius = size * (0.18 + i * 0.16)
      ctx.beginPath()
      ctx.setLineDash(i % 2 === 0 ? [14, 10] : [4, 8])
      ctx.arc(size / 2, size / 2, radius, 0, Math.PI * 2)
      ctx.stroke()
    }
    ctx.setLineDash([])
    ctx.strokeStyle = 'rgba(56,189,248,0.35)'
    ctx.lineWidth = 1
    for (let a = 0; a < 12; a++) {
      const angle = (a / 12) * Math.PI * 2
      ctx.beginPath()
      ctx.moveTo(size / 2 + Math.cos(angle) * size * 0.12, size / 2 + Math.sin(angle) * size * 0.12)
      ctx.lineTo(size / 2 + Math.cos(angle) * size * 0.46, size / 2 + Math.sin(angle) * size * 0.46)
      ctx.stroke()
    }
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  cachedHalo = texture
  return texture
}
