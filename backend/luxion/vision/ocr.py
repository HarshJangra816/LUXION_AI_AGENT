"""Text extraction from images (PRD §11 "OCR", §33.15, Phase 11b).

Two engines behind one contract, chosen by ``vision.ocr_engine``:

===============  ==========================================================  ===========
Engine           How it works                                                Cost
===============  ==========================================================  ===========
``rapidocr``     RapidOCR on ONNX Runtime — detection + recognition on the    free, local
                 box. Exact, deterministic, no model call.
``vision``       The configured vision model transcribes the picture.         one model call
                 Works even without the OCR package and reads messy
                 layout better, but is slow and approximate.
``auto``         Try RapidOCR first; fall back to the vision model when the
                 package is missing or finds nothing.
===============  ==========================================================  ===========

The fallback matters: ``rapidocr-onnxruntime`` is an **optional** dependency,
so a fresh install without it still answers OCR requests through the vision
model instead of failing.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from luxion.config.settings import Settings
from luxion.vision.analyzer import analyze_images
from luxion.vision.imaging import VisionError, decode_image, prepare_image

logger = logging.getLogger(__name__)

#: One RapidOCR instance per process — loading the ONNX session costs ~1 s.
_ENGINE: Any = None
_ENGINE_LOCK = threading.Lock()


def rapidocr_available() -> bool:
    """True when ``rapidocr-onnxruntime`` is importable."""
    try:
        import rapidocr_onnxruntime  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def _engine() -> Any:
    """Lazily build (and cache) the RapidOCR instance."""
    global _ENGINE  # noqa: PLW0603 - one shared, expensive ONNX session
    with _ENGINE_LOCK:
        if _ENGINE is None:
            try:
                from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
            except ImportError as exc:
                raise VisionError(
                    "RapidOCR is not installed (pip install rapidocr-onnxruntime) — "
                    "set vision.ocr_engine to 'vision' to transcribe with the model instead.",
                    code="ocr_engine_missing",
                ) from exc
            _ENGINE = RapidOCR()
        return _ENGINE


@dataclass(frozen=True)
class OcrItem:
    """One recognised text run with its four corner points."""

    text: str
    score: float
    box: list[list[float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "score": round(self.score, 3), "box": self.box}


@dataclass(frozen=True)
class OcrResult:
    """What one OCR pass returned, regardless of which engine ran."""

    text: str
    #: ``"rapidocr"`` or ``"vision"`` — which engine actually answered.
    engine: str
    #: Human label of the input (file name, ``"camera 0"``).
    source: str
    #: Per-line boxes; empty for the vision engine, which only returns prose.
    items: list[OcrItem] = field(default_factory=list)
    #: Wall-clock milliseconds for the engine itself.
    elapsed_ms: int = 0

    @property
    def line_count(self) -> int:
        return len([line for line in self.text.splitlines() if line.strip()])

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "engine": self.engine,
            "source": self.source,
            "line_count": self.line_count,
            "elapsed_ms": self.elapsed_ms,
            "items": [item.as_dict() for item in self.items],
        }


def _to_numpy(image: Any) -> Any:
    """PIL image → RGB ``uint8`` array, the shape RapidOCR expects."""
    import numpy as np  # noqa: PLC0415

    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.asarray(image)


def run_rapidocr(image: Any, *, source: str = "image") -> OcrResult:
    """Run RapidOCR over a PIL image (synchronous — offload with to_thread)."""
    import time  # noqa: PLC0415

    engine = _engine()
    started = time.perf_counter()
    output, _elapse = engine(_to_numpy(image))
    elapsed = int((time.perf_counter() - started) * 1000)

    items: list[OcrItem] = []
    for entry in output or []:
        # Each entry is [box, text, score]; the box is four [x, y] corners.
        try:
            box, text, score = entry[0], str(entry[1]), float(entry[2])
        except (TypeError, ValueError, IndexError):  # pragma: no cover - defensive
            continue
        items.append(
            OcrItem(
                text=text,
                score=score,
                box=[[float(x), float(y)] for x, y in box],
            )
            if box
            else OcrItem(text=text, score=score)
        )

    # RapidOCR preserves reading order only loosely — sort top-to-bottom, then
    # left-to-right so the joined text matches what a person reads.
    def _reading_order(item: OcrItem) -> tuple[float, float]:
        if not item.box:
            return (0.0, 0.0)
        return (round(item.box[0][1] / 12), item.box[0][0])

    items.sort(key=_reading_order)
    text = "\n".join(item.text for item in items)
    logger.info("ocr_rapidocr lines=%s ms=%s", len(items), elapsed)
    return OcrResult(text=text, engine="rapidocr", source=source, items=items, elapsed_ms=elapsed)


async def extract_text(
    settings: Settings,
    source: Any,
    *,
    engine: str | None = None,
    label: str | None = None,
) -> OcrResult:
    """Extract the text from ``source`` (path, bytes or PIL image).

    ``engine`` overrides ``vision.ocr_engine`` for this call. Raises
    :class:`~luxion.vision.imaging.VisionError` only when the requested
    engine genuinely cannot run — ``auto`` never raises, it just degrades.
    """
    chosen = (engine or settings.vision.ocr_engine).strip().lower()
    if chosen not in {"auto", "rapidocr", "vision"}:
        raise VisionError(
            f"Unknown OCR engine '{chosen}' — use 'auto', 'rapidocr' or 'vision'.",
            code="ocr_unknown_engine",
        )

    pil_image, name = await asyncio.to_thread(decode_image, source, label=label)

    if chosen in {"auto", "rapidocr"} and rapidocr_available():
        try:
            result = await asyncio.to_thread(run_rapidocr, pil_image, source=name)
        except VisionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface engine crashes as tool errors
            logger.warning("ocr_rapidocr_failed error=%s", exc)
            if chosen == "rapidocr":
                raise VisionError(
                    f"RapidOCR failed on this image: {exc}",
                    code="ocr_engine_failed",
                ) from exc
            result = None
        if result is not None and (result.text.strip() or chosen == "rapidocr"):
            return result

    if chosen == "rapidocr":
        raise VisionError(
            "RapidOCR is not installed (pip install rapidocr-onnxruntime).",
            code="ocr_engine_missing",
        )

    # Vision fallback (also the plain 'vision' engine).
    if not settings.vision.enabled:
        raise VisionError(
            "RapidOCR is unavailable and vision is turned off, so there is no "
            "engine to read this image. Enable vision in Settings → Vision or "
            "install rapidocr-onnxruntime.",
            code="vision_disabled",
        )
    answer = await analyze_images(
        settings,
        [await asyncio.to_thread(prepare_image, pil_image, label=name)],
        question=settings.vision.ocr_prompt,
    )
    return OcrResult(text=answer, engine="vision", source=name, items=[], elapsed_ms=0)


__all__ = ["OcrItem", "OcrResult", "extract_text", "rapidocr_available", "run_rapidocr"]
