"""Microphone capture, energy VAD and interruptible playback (PRD §5.5, §26).

Everything here is either pure (segmenter, resampling, levels — unit-testable
without hardware) or a thin wrapper over sounddevice. The PortAudio callback
in :class:`SoundMic` never blocks: it hands finished blocks to a sink and
returns.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

#: Whisper consumes 16 kHz mono float32; capture may run at the device rate.
TARGET_RATE = 16_000


class AudioError(RuntimeError):
    """Device, capture or playback failure surfaced to the voice manager."""


def rms(block: np.ndarray) -> float:
    """Normalized RMS level of a float32 block (speech ≈ 0.02–0.3)."""
    if block.size == 0:
        return 0.0
    values = block.astype(np.float64, copy=False)
    return float(np.sqrt(np.mean(values * values)))


def resample(block: np.ndarray, src_rate: int, dst_rate: int = TARGET_RATE) -> np.ndarray:
    """Linear-resample a mono block to the STT rate (no-op when equal)."""
    if block.size == 0:
        return np.zeros(0, dtype=np.float32)
    if src_rate <= 0 or src_rate == dst_rate:
        return block.astype(np.float32, copy=False)
    target = max(1, int(round(block.size * dst_rate / src_rate)))
    positions = np.linspace(0.0, float(block.size - 1), target)
    source = np.arange(block.size, dtype=np.float64)
    return np.interp(positions, source, block).astype(np.float32)


class Segmenter:
    """Energy voice-activity segmentation with an adaptive noise floor.

    ``feed`` is called once per captured block: ``"start"`` marks the moment
    speech has held above the gate for ``min_speech_s``, ``"end"`` marks
    ``silence_s`` of quiet after an open utterance. The floor tracks ambient
    noise only while idle, so a loud room raises the gate instead of feeding
    the STT a endless stream of room tone.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.01,
        min_speech_s: float = 0.2,
        silence_s: float = 0.9,
    ) -> None:
        self.threshold = threshold
        self.min_speech_s = min_speech_s
        self.silence_s = silence_s
        self.noise_floor = threshold
        self.active = False
        self.speech_seconds = 0.0
        self._speech_run = 0.0
        self._silence_run = 0.0

    @property
    def gate(self) -> float:
        """Effective speech threshold: config floor or learned ambient × 2.5."""
        return max(self.threshold, self.noise_floor * 2.5)

    def reset(self) -> None:
        """Close the current utterance but keep the learned ambient floor."""
        self.active = False
        self.speech_seconds = 0.0
        self._speech_run = 0.0
        self._silence_run = 0.0

    def feed(self, level: float, dt: float) -> str | None:
        """Advance the detector by one block; returns ``"start"``/``"end"``/``None``."""
        if not self.active:
            if level >= self.gate:
                self._speech_run += dt
                if self._speech_run >= self.min_speech_s:
                    self.active = True
                    self._silence_run = 0.0
                    self.speech_seconds = 0.0
                    return "start"
            else:
                self._speech_run = 0.0
                self.noise_floor += 0.03 * (level - self.noise_floor)
            return None
        if level >= self.gate:
            self._silence_run = 0.0
            self.speech_seconds += dt
            return None
        self._silence_run += dt
        if self._silence_run >= self.silence_s:
            self.reset()
            return "end"
        return None


# ------------------------------------------------------------------ capture
class SoundMic:
    """Mono float32 capture on a PortAudio input stream."""

    def __init__(
        self,
        sink: Callable[[np.ndarray], None],
        *,
        device: int | None = None,
        rate: int = TARGET_RATE,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self._sink = sink
        self._device = device
        self._rate = rate
        self._on_level = on_level
        self._stream: Any = None

    @property
    def rate(self) -> int:
        """The rate PortAudio actually opened (may differ after fallback)."""
        return self._rate

    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None and getattr(self._stream, "active", False):
            return

        def _callback(indata: np.ndarray, _frames: int, _time: Any, status: Any) -> None:
            if status:
                logger.debug("mic_status", extra={"status": str(status)})
            block = indata[:, 0] if indata.ndim > 1 else indata
            block = block.astype(np.float32, copy=True)
            if self._on_level is not None:
                self._on_level(rms(block))
            self._sink(block)

        try:
            stream = sd.InputStream(
                samplerate=self._rate,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=_callback,
            )
            if not stream.active:
                stream.start()
        except Exception as exc:  # PortAudio raises a bare Exception subclass
            raise AudioError(f"Could not open microphone: {exc}") from exc
        self._stream = stream
        try:
            self._rate = int(stream.samplerate)
        except Exception:  # noqa: BLE001 - keep the requested rate as-is
            pass

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            logger.debug("mic_stop_failed", exc_info=True)


def list_input_devices() -> list[dict[str, Any]]:
    """Every available input device plus which one the system picks."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioError("sounddevice is not installed") from exc
    try:
        devices = sd.query_devices()
        default = sd.default.device[0]
    except Exception as exc:
        raise AudioError(f"Could not query audio devices: {exc}") from exc
    return [
        {
            "index": index,
            "name": str(device["name"]),
            "channels": int(device["max_input_channels"]),
            "rate": float(device["default_samplerate"]),
            "is_default": index == default,
        }
        for index, device in enumerate(devices)
        if device["max_input_channels"] > 0
    ]


def resolve_input_device(spec: int | str | None) -> tuple[int | None, str]:
    """Turn a configured device spec into ``(index, label)``.

    ``None``/``""`` picks the system default, an integer is a PortAudio index
    and a string matches device names case-insensitively (indices shift across
    reboots and USB reconnects, names survive).
    """
    devices = list_input_devices()
    if spec is None or spec == "" or (isinstance(spec, str) and not spec.strip()):
        default = next((dev for dev in devices if dev["is_default"]), None)
        if default is None and devices:
            default = devices[0]
        if default is None:
            raise AudioError("No microphone input devices are available")
        return int(default["index"]), str(default["name"])
    if isinstance(spec, bool):
        raise AudioError("Invalid device specification")
    if isinstance(spec, (int, np.integer)) or (
        isinstance(spec, str) and spec.strip().lstrip("-").isdigit()
    ):
        index = int(spec)
        for dev in devices:
            if dev["index"] == index:
                return index, str(dev["name"])
        raise AudioError(f"Input device {index} is not available")
    needle = str(spec).casefold()
    for dev in devices:
        if needle in str(dev["name"]).casefold():
            return int(dev["index"]), str(dev["name"])
    raise AudioError(f"No input device matching {spec!r}")


# ----------------------------------------------------------------- playback
def play_wav(
    data: bytes,
    stop: threading.Event,
    *,
    on_block: Callable[[], None] | None = None,
) -> bool:
    """Stream 16-bit PCM WAV bytes to the default output.

    Returns ``False`` when ``stop`` fired before the last block — that is how
    the manager detects a voice interruption (PRD §26). ``on_block`` runs
    between blocks so the caller can watch the microphone for a barge-in.
    """
    if not data:
        return True
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error as exc:
        raise AudioError(f"TTS produced an invalid WAV file: {exc}") from exc
    if width != 2:
        raise AudioError(f"Unsupported WAV sample width: {width}")
    audio = np.frombuffer(frames, dtype=np.int16)
    if audio.size == 0:
        return True
    block_size = max(1, int(rate * 0.15))
    import sounddevice as sd

    try:
        with sd.OutputStream(samplerate=rate, channels=channels, dtype="int16") as out:
            for start in range(0, audio.size, block_size):
                if stop.is_set():
                    return False
                if on_block is not None:
                    on_block()
                chunk = audio[start : start + block_size]
                out.write(chunk.reshape(-1, channels) if channels > 1 else chunk)
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError(f"Playback failed: {exc}") from exc
    return True
