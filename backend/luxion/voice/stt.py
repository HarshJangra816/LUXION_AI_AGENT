"""Speech-to-text via faster-whisper (PRD §5.5).

The model downloads from the Hugging Face hub on first use and is then kept
loaded for the lifetime of the worker thread. Loading is explicit (``load``)
so the voice manager can report a warm-up state instead of blocking a route.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from luxion.voice.audio import TARGET_RATE

logger = logging.getLogger(__name__)


class SttError(RuntimeError):
    """Model missing, unloadable or failed mid-transcription."""


class WhisperStt:
    """faster-whisper recognizer with a lazily loaded, cached model."""

    def __init__(
        self,
        model_name: str = "base.en",
        *,
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        #: "" = auto-detect; ``.en`` models force English regardless.
        self.language = language
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def resolved_language(self) -> str | None:
        if self.language:
            return self.language
        if self.model_name.endswith(".en"):
            return "en"
        return None

    def load(self) -> None:
        """Download (first call) and load the model; idempotent."""
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SttError("faster-whisper is not installed") from exc
            device = self.device
            compute = self.compute_type
            if device == "auto":
                device = "cpu"
                compute = "int8"
            elif device == "cuda" and compute == "int8":
                compute = "float16"
            try:
                logger.info("stt_loading", extra={"model": self.model_name, "device": device})
                self._model = WhisperModel(self.model_name, device=device, compute_type=compute)
            except Exception as exc:
                raise SttError(
                    f"Could not load the speech model '{self.model_name}': {exc}"
                ) from exc
            logger.info("stt_ready", extra={"model": self.model_name})

    def transcribe(self, audio: np.ndarray) -> str:
        """16 kHz mono float32 audio → recognized text ("" when silent)."""
        if audio.size == 0:
            return ""
        self.load()
        try:
            segments, _info = self._model.transcribe(
                audio,
                language=self.resolved_language,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
        except SttError:
            raise
        except Exception as exc:
            raise SttError(f"Speech recognition failed: {exc}") from exc
