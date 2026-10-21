"""Vision + hardware package (PRD §5.9, §11, §33.15, §39, Phase 11).

Phase 11 splits into pieces that build on each other:

``imaging``
    Decode, downscale and encode images (Pillow only). Everything else in the
    package starts here.
``analyzer``
    Hand an image to the configured vision model through the existing
    provider contract — no second LLM stack.
``camera``
    Webcam capture through OpenCV (the single dependency Phase 11b adds).
``ocr``
    Text extraction: RapidOCR when installed, the vision model otherwise.
``auth``
    Voice + face second factors (Phase 11c).
"""

from __future__ import annotations

from luxion.vision.analyzer import analyze_images, probe_vision, resolve_vision_llm
from luxion.vision.camera import capture_image, list_cameras
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image
from luxion.vision.ocr import OcrResult, extract_text, rapidocr_available

__all__ = [
    "OcrResult",
    "PreparedImage",
    "VisionError",
    "analyze_images",
    "capture_image",
    "extract_text",
    "list_cameras",
    "prepare_image",
    "probe_vision",
    "rapidocr_available",
    "resolve_vision_llm",
]
