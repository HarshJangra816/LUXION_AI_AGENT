"""Vision + hardware package (PRD §5.9, §33.15, §39, Phase 11).

Phase 11 splits into three pieces that build on each other:

``imaging``
    Decode, downscale and encode images (Pillow only).
``analyzer``
    Hand an image to the configured vision model through the existing
    provider contract — no new Python dependency.
``camera`` / ``ocr`` / ``auth``
    The hardware half: webcam capture, text extraction and the biometric
    second factors.
"""

from __future__ import annotations

from luxion.vision.analyzer import (
    analyze_images,
    probe_vision,
    resolve_vision_llm,
)
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image

__all__ = [
    "PreparedImage",
    "VisionError",
    "analyze_images",
    "prepare_image",
    "probe_vision",
    "resolve_vision_llm",
]
