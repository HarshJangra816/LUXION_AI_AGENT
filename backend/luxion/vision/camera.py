"""Webcam capture through OpenCV (PRD §11 "Camera", §39 hardware access).

OpenCV is the **one** dependency Phase 11b adds. It buys the webcam, the
face detector and — in Phase 11c — face recognition from a single wheel, so
the rest of the phase keeps the FOSS-first, no-extra-stack diet.

Everything here is synchronous and CPU-only: OpenCV's ``VideoCapture`` blocks,
so callers run it through :func:`asyncio.to_thread`. The device is always
released, including on error, because a leaked handle keeps the webcam's
"on" light lit on Windows until the process dies.

Capability gate: ``capture_camera`` (the tool) declares
``requires="camera"``, so :mod:`luxion.security.capabilities` decides first
and a denial is a hard block no autonomy level can override (PRD §39).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from luxion.config.settings import Settings
from luxion.vision.imaging import PreparedImage, VisionError, prepare_image

logger = logging.getLogger(__name__)

#: Device indices probed by :func:`list_cameras`. Windows usually reports the
#: first webcam as 0; probing a few extra spots finds USB cameras that lost
#: the race at boot.
PROBE_INDICES: tuple[int, ...] = (0, 1, 2, 3)


def _cv2() -> Any:
    """Import OpenCV lazily so the module import stays cheap."""
    try:
        import cv2  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - installed with the backend
        raise VisionError(
            "OpenCV is required for camera capture (pip install opencv-contrib-python).",
            code="camera_dependency_missing",
        ) from exc
    return cv2


def opencv_available() -> bool:
    """True when OpenCV is importable. Never touches a device.

    This is the cheap status check: it does **not** open the webcam, because
    doing so would light the camera indicator every time Settings loads.
    """
    try:
        _cv2()
    except VisionError:
        return False
    return True


def camera_available() -> bool:
    """True when OpenCV is importable *and* at least one device opens."""
    try:
        cv2 = _cv2()
    except VisionError:
        return False
    capture = cv2.VideoCapture(0)
    try:
        return bool(capture.isOpened())
    finally:
        capture.release()


def list_cameras() -> list[int]:
    """Return the indices that actually open a device (opens each briefly).

    Cheap and synchronous — call it through :func:`asyncio.to_thread` from a
    request handler. Never raises: a broken driver reports no cameras.
    """
    try:
        cv2 = _cv2()
    except VisionError:
        return []
    found: list[int] = []
    for index in PROBE_INDICES:
        capture = cv2.VideoCapture(index)
        try:
            if capture.isOpened():
                found.append(index)
        finally:
            capture.release()
    return found


def capture_frame(
    *,
    index: int = 0,
    width: int = 1280,
    height: int = 720,
    warmup_frames: int = 3,
) -> Any:
    """Grab one BGR frame from the webcam.

    The first frames out of a cold sensor are usually black or badly exposed,
    so ``warmup_frames`` reads are discarded before the one we keep.
    Raises :class:`~luxion.vision.imaging.VisionError` with a distinct
    ``camera_*`` code for every failure mode, so the tool can tell the user
    "no camera" apart from "camera is in use".
    """
    cv2 = _cv2()
    capture = cv2.VideoCapture(index)
    try:
        if not capture.isOpened():
            raise VisionError(
                f"Camera {index} could not be opened. It may be missing, busy in "
                "another app, or blocked in Windows → Privacy → Camera.",
                code="camera_open_failed",
            )

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(max(0, warmup_frames)):
            capture.read()

        frame = None
        for _ in range(3):  # a single dropped read must not fail the capture
            ok, candidate = capture.read()
            if ok and candidate is not None and candidate.size:
                frame = candidate
                break
        if frame is None:
            raise VisionError(
                f"Camera {index} opened but returned no frame.",
                code="camera_no_frame",
            )
        return frame
    finally:
        # Released on every path — including a failed open, where the handle
        # still counts against the driver.
        capture.release()


def frame_to_image(frame: Any) -> Any:
    """Convert an OpenCV BGR frame into a PIL image."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    rgb = frame[:, :, ::-1]
    return Image.fromarray(np.ascontiguousarray(rgb))


def save_frame(frame: Any, destination: Path) -> int:
    """Write a BGR frame to ``destination`` as PNG; returns the byte size."""
    cv2 = _cv2()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), frame):  # type: ignore[call-overload]
        raise VisionError(
            f"Could not write the captured frame to {destination.name}.",
            code="camera_write_failed",
        )
    return destination.stat().st_size


async def capture_image(
    settings: Settings,
    *,
    save_to: Path | None = None,
    label: str | None = None,
) -> tuple[PreparedImage, tuple[int, int], Path | None]:
    """Capture the webcam and prepare it for the vision model.

    Returns ``(image, (width, height), saved_path)`` — the saved path is
    ``None`` unless ``save_to`` was given. Runs the blocking capture off the
    event loop.
    """
    vision = settings.vision
    frame = await asyncio.to_thread(
        capture_frame,
        index=vision.camera_index,
        width=vision.camera_width,
        height=vision.camera_height,
        warmup_frames=vision.camera_warmup_frames,
    )
    height, width = frame.shape[:2]

    image = await asyncio.to_thread(frame_to_image, frame)
    prepared = await asyncio.to_thread(
        prepare_image,
        image,
        max_dimension=vision.max_dimension,
        max_bytes=vision.max_bytes,
        label=label or f"camera {vision.camera_index}",
    )

    saved: Path | None = None
    if save_to is not None:
        written = await asyncio.to_thread(save_frame, frame, save_to)
        saved = save_to
        logger.info(
            "camera_capture index=%s size=%sx%s bytes=%s",
            vision.camera_index,
            width,
            height,
            written,
        )
    return prepared, (width, height), saved


__all__ = [
    "PROBE_INDICES",
    "camera_available",
    "capture_frame",
    "capture_image",
    "frame_to_image",
    "list_cameras",
    "opencv_available",
    "save_frame",
]
