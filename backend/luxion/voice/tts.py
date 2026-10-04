"""Text-to-speech providers behind one abstraction (PRD §5.6).

Providers named in the PRD: Piper, Windows TTS, cloud TTS. Two ship today -
the offline Windows (SAPI5) backend and OmniVoice, a local neural TTS with
voice design prompts - and ``get_tts`` is the switchboard the others plug
into.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from luxion.config.settings import VoiceConfig

logger = logging.getLogger(__name__)


class TtsError(RuntimeError):
    """Synthesis failed; the reply stays visible as text."""


#: pyttsx3 keeps ONE cached engine per driver with a shared run loop, so every
#: synthesis — worker thread, route thread, tests — serializes through here.
_SYNTH_LOCK = threading.Lock()


def speechify(text: str) -> str:
    """Flatten markdown-ish reply text into something natural to speak."""
    if not text.strip():
        return ""
    out = re.sub(r"```.*?```", " Code is shown in the chat. ", text, flags=re.DOTALL)
    out = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"`([^`]+)`", r"\1", out)
    out = re.sub(r"(\*\*|__|~~)", "", out)
    out = re.sub(r"\*([^*]+)\*", r"\1", out)
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*>\s?", "", out, flags=re.MULTILINE)
    out = out.replace("|", ",")
    out = re.sub(r"\s+", " ", out)
    return out.strip()


class TtsProvider(Protocol):
    """A speech backend (PRD §5.6 provider abstraction)."""

    name: str

    def synthesize(self, text: str, *, rate: int = 0, volume: int = 100) -> bytes:
        """Return ``text`` spoken aloud as a WAV byte string."""


class WindowsTts:
    """Offline SAPI5 voices through pyttsx3 (PRD §5.6 "Windows TTS")."""

    name = "windows"

    def synthesize(self, text: str, *, rate: int = 0, volume: int = 100) -> bytes:
        speak = speechify(text)
        if not speak:
            raise TtsError("Nothing to speak")
        try:
            import pyttsx3
        except ImportError as exc:
            raise TtsError("pyttsx3 is not installed") from exc
        with _SYNTH_LOCK, tempfile.TemporaryDirectory(prefix="luxion-tts-") as tmp:
            path = Path(tmp) / "reply.wav"
            engine = pyttsx3.init()
            try:
                base_rate = int(engine.getProperty("rate") or 200)
                engine.setProperty("rate", max(80, min(450, base_rate + rate)))
                engine.setProperty("volume", max(0.0, min(1.0, volume / 100.0)))
                engine.save_to_file(speak, str(path))
                engine.runAndWait()
            finally:
                with contextlib.suppress(Exception):  # teardown is best-effort
                    engine.stop()
            data = path.read_bytes() if path.exists() else b""
        if not data:
            raise TtsError("Synthesis produced no audio")
        return data


#: Fall back to this model when no ``voice.tts_model`` is configured.
DEFAULT_OMNI_MODEL = "k2-fsa/OmniVoice"


class OmniVoiceTts:
    """Local neural TTS through the installed ``omnivoice`` package.

    Synthesis runs entirely offline. The voice itself comes from a *voice
    design* prompt ("female, british accent, moderate pitch") rather than a
    reference clip, so no sample audio has to be stored. ``tts_rate`` maps
    onto OmniVoice's own ``speed`` factor instead of resampling afterwards,
    which keeps the pitch natural.
    """

    name = "omnivoice"

    def __init__(
        self,
        model_name: str = DEFAULT_OMNI_MODEL,
        *,
        instruct: str = "",
        steps: int = 8,
        device: str = "cpu",
        language: str = "",
    ) -> None:
        self.model_name = model_name
        self.instruct = instruct
        self.steps = steps
        self.device = device
        self.language = language
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def configure(self, *, instruct: str, steps: int, language: str) -> None:
        """Refresh the cheap knobs; weights stay loaded."""
        self.instruct = instruct
        self.steps = steps
        self.language = language

    def load(self) -> None:
        """Download (first call) and load the model; idempotent."""
        with self._lock:
            if self._model is not None:
                return
            try:
                from omnivoice import OmniVoice
            except ImportError as exc:
                raise TtsError(
                    "omnivoice is not installed (pip install omnivoice); "
                    "switch the TTS provider back to 'windows'"
                ) from exc
            try:
                logger.info("tts_loading", extra={"model": self.model_name, "device": self.device})
                self._model = OmniVoice.from_pretrained(self.model_name, device_map=self.device)
            except Exception as exc:
                raise TtsError(
                    f"Could not load the voice model '{self.model_name}': {exc}"
                ) from exc
            logger.info("tts_ready", extra={"model": self.model_name})

    def synthesize(self, text: str, *, rate: int = 0, volume: int = 100) -> bytes:
        """``text`` spoken by the designed voice, as a 16-bit WAV."""
        speak = speechify(text)
        if not speak:
            raise TtsError("Nothing to speak")
        self.load()
        # rate -50..+100 (SAPI wording) -> speed 0.5..2.0 for OmniVoice.
        speed = max(0.5, min(2.0, 1.0 + rate / 100.0))
        try:
            chunks = self._model.generate(
                text=speak,
                instruct=self.instruct or None,
                language=self.language or None,
                num_step=self.steps,
                speed=speed,
            )
        except Exception as exc:  # noqa: BLE001 - the reply still shows as text
            raise TtsError(f"Voice synthesis failed: {exc}") from exc
        if not chunks:
            raise TtsError("Synthesis produced no audio")
        audio = np.asarray(chunks[0], dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise TtsError("Synthesis produced no audio")
        gain = max(0.0, min(1.0, volume / 100.0))
        if gain != 1.0:
            audio = np.clip(audio * gain, -1.0, 1.0)
        return _encode_wav(audio, int(getattr(self._model, "sampling_rate", 24_000)))


def _encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 mono -> in-memory PCM WAV bytes."""
    try:
        import soundfile as sf
    except ImportError as exc:
        raise TtsError("soundfile is not installed") from exc
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def get_tts(provider: str, *, voice: VoiceConfig | None = None) -> TtsProvider:
    """Resolve a configured TTS provider (PRD §5.6 abstraction).

    ``voice`` carries the knobs a provider needs before it can synthesize
    (OmniVoice's model, prompt and step count); omitting it uses defaults.
    """
    if provider == "windows":
        return WindowsTts()
    if provider == "omnivoice":
        return _omnivoice(voice)
    raise TtsError(f"Unknown TTS provider '{provider}' (expected 'windows' or 'omnivoice')")


#: The heaviest part of OmniVoice is loading weights, so one instance per
#: model id is reused for the life of the process; the cheap knobs (prompt,
#: steps, language) are refreshed on every call instead of reloading.
_OMNI_CACHE: dict[str, OmniVoiceTts] = {}
_OMNI_CACHE_LOCK = threading.Lock()


def _omnivoice(voice: VoiceConfig | None) -> OmniVoiceTts:
    model = (voice.tts_model if voice else "").strip() or DEFAULT_OMNI_MODEL
    with _OMNI_CACHE_LOCK:
        provider = _OMNI_CACHE.get(model)
        if provider is None:
            provider = OmniVoiceTts(model_name=model)
            _OMNI_CACHE[model] = provider
    provider.configure(
        instruct=(voice.tts_instruct if voice else "").strip(),
        steps=int(voice.tts_steps) if voice and voice.tts_steps else 8,
        language=(voice.tts_language if voice else "").strip(),
    )
    return provider


def reset_tts_cache() -> None:
    """Drop cached provider instances (tests / a model change)."""
    with _OMNI_CACHE_LOCK:
        _OMNI_CACHE.clear()
