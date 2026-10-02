"""Text-to-speech providers behind one abstraction (PRD §5.6).

Providers named in the PRD: Piper, Windows TTS, cloud TTS. This phase ships
the offline Windows (SAPI5) backend; ``get_tts`` is the switchboard the other
providers will plug into.
"""

from __future__ import annotations

import contextlib
import logging
import re
import tempfile
import threading
from pathlib import Path
from typing import Protocol

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


def get_tts(provider: str) -> TtsProvider:
    """Resolve a configured TTS provider (PRD §5.6 abstraction)."""
    if provider == "windows":
        return WindowsTts()
    raise TtsError(f"Unknown TTS provider '{provider}' (expected 'windows')")
