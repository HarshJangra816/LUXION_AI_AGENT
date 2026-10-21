/**
 * Vision status + settings access.
 *
 * Powers the Settings → Vision card (PRD §5.9/§33.15, Phase 11). Mirrors
 * `backend/luxion/api/routes/vision.py`. The vision tools (`analyze_image`,
 * `analyze_screenshot`) run from chat; the card only tunes policy, points
 * Luxion at a vision model and proves the setup really works.
 */

import { request } from './api'

/** Every knob `PUT /vision/config` accepts (backend VisionConfig). */
export interface VisionConfig {
  enabled: boolean
  model: string
  provider: string
  base_url: string
  api_key_env: string
  prompt: string
  max_images: number
  max_dimension: number
  max_bytes: number
  timeout_s: number
  camera_index: number
  camera_width: number
  camera_height: number
  camera_warmup_frames: number
  ocr_engine: 'auto' | 'rapidocr' | 'vision'
  ocr_prompt: string
}

/** Static facts about the vision family (backend routes/vision._status). */
export interface VisionStatus {
  enabled: boolean
  /** True — the vision call reuses the chat provider, so no new key. */
  keyless: boolean
  /** True — no browser and no extra Python dependency for the model call. */
  browser_independent: boolean
  /** True — the vision model runs on the chat adapter's endpoint. */
  uses_chat_provider: boolean
  /** OpenCV importable (import check only — never opens the camera). */
  opencv_available: boolean
  /** RapidOCR importable. */
  ocr_available: boolean
}

/** Enumerations the card offers as hints (backend routes/vision._catalog). */
export interface VisionCatalog {
  suggested_models: string[]
  supported_types: string[]
  max_images: number
  ocr_engines: Array<'auto' | 'rapidocr' | 'vision'>
  camera_max_index: number
}

/** What Settings → Vision edits (effective + defaults + status + catalog). */
export interface VisionConfigBundle {
  config: VisionConfig
  defaults: VisionConfig
  status: VisionStatus
  catalog: VisionCatalog
}

/** Reachability of the vision endpoint (`POST /vision/probe`). */
export interface VisionProbe {
  ok: boolean
  provider: string
  model: string
  models: string[]
  found: boolean
  error: string | null
}

/** The answer to one analysis (`POST /vision/analyze`). */
export interface VisionAnalysis {
  answer: string
  path: string | null
  image: {
    source: string
    mime: string
    width: number
    height: number
    bytes: number
  }
}

/** Which webcam indices opened a device (`POST /vision/cameras`). */
export interface CameraList {
  indices: number[]
  camera_index: number
}

/** A captured frame (`POST /vision/camera`). */
export interface CameraCapture {
  image: string
  mime: string
  width: number
  height: number
  path: string | null
  answer: string | null
}

/** One OCR item with a bounding box and confidence (`POST /vision/ocr`). */
export interface OcrItem {
  text: string
  score: number
  box: number[][]
}

/** Extracted text (`POST /vision/ocr`). */
export interface OcrResult {
  text: string
  engine: string
  source: string
  line_count: number
  elapsed_ms: number
  items: OcrItem[]
  path?: string
}

/** Effective vision settings + endpoint status (defaults → `.env` → vision.json). */
export function getVisionConfig(signal?: AbortSignal): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision', { signal })
}

/** Persist the Settings → Vision edits. */
export function setVisionConfig(patch: Partial<VisionConfig>): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

/** Drop `vision.json` so `.env` / built-in defaults win again. */
export function resetVisionConfig(): Promise<VisionConfigBundle> {
  return request<VisionConfigBundle>('/vision/config', { method: 'DELETE' })
}

/** Check that the vision endpoint is reachable and knows the model. */
export function probeVision(): Promise<VisionProbe> {
  return request<VisionProbe>('/vision/probe', { method: 'POST' })
}

/** Look at an image file (or the screen) and return the model's answer. */
export function analyzeImage(payload: {
  path?: string
  screenshot?: boolean
  question?: string
}): Promise<VisionAnalysis> {
  return request<VisionAnalysis>('/vision/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Probe which webcams open (opt-in — never on page load). */
export function listCameras(): Promise<CameraList> {
  return request<CameraList>('/vision/cameras', { method: 'POST' })
}

/** Capture one frame from the webcam. */
export function captureCamera(payload: {
  question?: string
  path?: string
} = {}): Promise<CameraCapture> {
  return request<CameraCapture>('/vision/camera', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Read the text out of an image file. */
export function ocrImage(payload: {
  path: string
  engine?: 'auto' | 'rapidocr' | 'vision'
}): Promise<OcrResult> {
  return request<OcrResult>('/vision/ocr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
