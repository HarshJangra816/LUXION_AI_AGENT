"""Image loading, downscaling and encoding for the vision tools (Phase 11).

Pure Pillow — **no new Python dependency**. Everything in this module is
CPU-cheap and never touches the network.

The pipeline is always the same:

1. decode the source (path, raw bytes or an in-memory PIL image),
2. apply the EXIF rotation and drop to a sane colour mode,
3. downscale so the longest edge is at most ``max_dimension``,
4. encode (PNG first, JPEG when the PNG is too big) and base64 it.

Step 3 matters: the vision models rescale to a few hundred pixels anyway, and
a 4K screenshot would otherwise cost megabytes of prompt budget for nothing.
"""

from __future__ import annotations

import base64
import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luxion.llm.types import ImagePayload

#: Extensions Luxion will try to decode.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)

MIME_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

#: JPEG quality ladder used when the PNG is over the byte budget.
_JPEG_QUALITIES: tuple[int, ...] = (90, 80, 65, 50, 35)


class VisionError(Exception):
    """A vision failure the model should see as a tool error."""

    def __init__(self, message: str, *, code: str = "vision_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedImage:
    """One image ready to be handed to a vision model."""

    data: str
    mime: str
    width: int
    height: int
    #: Human label for logs and tool output (``"screenshot.png"``).
    source: str
    #: Size of the encoded payload in bytes.
    size_bytes: int

    def as_payload(self) -> ImagePayload:
        """The provider-agnostic attachment (base64, no ``data:`` prefix)."""
        return ImagePayload(data=self.data, mime=self.mime)

    def describe(self) -> dict[str, Any]:
        """Short summary for tool results and the API."""
        return {
            "source": self.source,
            "mime": self.mime,
            "width": self.width,
            "height": self.height,
            "bytes": self.size_bytes,
        }


def _pil():
    """Import Pillow lazily so the module import stays cheap."""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - Pillow is a hard dependency
        raise VisionError(
            "Pillow is required for image handling (pip install pillow).",
            code="vision_dependency_missing",
        ) from exc
    return Image


def load_image(path: str | Path) -> Any:
    """Decode an image file into a PIL image."""
    pil = _pil()
    target = Path(path)
    if not target.exists():
        raise VisionError(f"Image not found: {target}", code="vision_not_found")
    if target.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise VisionError(
            f"Unsupported image type '{target.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
            code="vision_unsupported_type",
        )
    try:
        image = pil.open(target)
        image.load()
    except VisionError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow raises many error types
        raise VisionError(
            f"Could not read image '{target.name}': {exc}",
            code="vision_decode_failed",
        ) from exc
    return image


def _normalise(image: Any) -> Any:
    """Apply the EXIF rotation and settle on a colour mode we can encode."""
    from PIL import ImageOps  # noqa: PLC0415

    with contextlib.suppress(Exception):  # a broken EXIF block must not be fatal
        image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    return image


def encode_image(image: Any, *, max_bytes: int = 8_000_000) -> tuple[bytes, str]:
    """Encode a PIL image, shrinking the format until it fits ``max_bytes``.

    Returns ``(payload, mime)``. PNG is preferred (lossless, keeps text
    crisp); JPEG is the fallback when the PNG is still too heavy.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    if len(payload) <= max_bytes:
        return payload, "image/png"

    if image.mode == "RGBA":
        image = image.convert("RGB")
    for quality in _JPEG_QUALITIES:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        payload = buffer.getvalue()
        if len(payload) <= max_bytes:
            return payload, "image/jpeg"

    raise VisionError(
        f"Image is too large to send ({len(payload)} bytes after compression, "
        f"budget {max_bytes}). Downscale it or raise vision.max_bytes.",
        code="vision_too_large",
    )


def prepare_image(
    source: str | Path | bytes | Any,
    *,
    max_dimension: int = 1568,
    max_bytes: int = 8_000_000,
    label: str | None = None,
) -> PreparedImage:
    """Turn any supported source into a :class:`PreparedImage`.

    ``source`` may be a file path, raw encoded bytes, or an already-decoded
    PIL image. The result is downscaled to ``max_dimension`` on its longest
    edge and base64-encoded, ready for :class:`ImagePayload`.
    """
    pil = _pil()
    image, name = decode_image(source, label=label)
    image = _normalise(image)
    image.thumbnail((max_dimension, max_dimension), pil.LANCZOS)
    payload, mime = encode_image(image, max_bytes=max_bytes)
    return PreparedImage(
        data=base64.b64encode(payload).decode("ascii"),
        mime=mime,
        width=image.width,
        height=image.height,
        source=name,
        size_bytes=len(payload),
    )


def decode_image(source: str | Path | bytes | Any, *, label: str | None = None) -> tuple[Any, str]:
    """Turn any supported source into a PIL image plus a human label.

    Shared by every consumer that wants the raw pixels rather than an encoded
    payload — :func:`prepare_image` for the vision model, the OCR engine for
    text extraction and the face detector in Phase 11c. The EXIF rotation and
    colour-mode fix are deliberately **not** applied here: OCR and face
    detection want the pixels as stored, and :func:`prepare_image` runs them
    for the model path.
    """
    pil = _pil()
    name = label
    if isinstance(source, (str, Path)):
        image = load_image(source)
        name = name or Path(source).name
    elif isinstance(source, (bytes, bytearray)):
        try:
            image = pil.open(io.BytesIO(bytes(source)))
            image.load()
        except Exception as exc:  # noqa: BLE001 - Pillow raises many error types
            raise VisionError(
                f"Could not decode the image bytes: {exc}",
                code="vision_decode_failed",
            ) from exc
        name = name or "image"
    elif hasattr(source, "size") and hasattr(source, "mode"):
        image = source
        name = name or "image"
    else:
        raise VisionError(
            "Unsupported image source — pass a file path, image bytes or a PIL image.",
            code="vision_unsupported_source",
        )
    return image, name


def guess_mime(path: str | Path) -> str:
    """MIME type for a file path (falls back to PNG)."""
    return MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "image/png")
