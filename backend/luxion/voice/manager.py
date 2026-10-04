"""The voice session: mic → VAD → STT → wake word → events → TTS (PRD §26).

Phase 4 ships the pipeline as a *backend service* the UI drives:

* ``start_listening`` opens the microphone and runs continuous segmentation.
  Finished utterances are transcribed on a worker thread and, once the wake
  phrase is satisfied, published as a ``command`` event — the frontend turns
  that into a normal chat turn (so the agent, its tools and its permissions
  are unchanged) and hands the reply back to :meth:`VoiceManager.speak`.
* ``recognize`` is push-to-talk: one utterance, no wake word, one transcript.
* ``speak`` synthesizes with the configured TTS provider and streams the WAV
  to the default output. While it plays, the capture loop can cut it off
  (``barge_in``) — PRD §26 voice interruption.

Every transition is broadcast on an asyncio queue consumed by
``GET /api/voice/events``. Nothing here touches FastAPI: routes only marshal.

Hardware gates are **not** optional — :meth:`_require_capability` consults
:mod:`luxion.security.capabilities` before the microphone or speaker is used,
so a denied capability is a hard block no autonomy level can override.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from luxion.config.settings import Settings, get_settings
from luxion.security.capabilities import get_capabilities
from luxion.voice.audio import (
    TARGET_RATE,
    AudioError,
    Segmenter,
    SoundMic,
    list_input_devices,
    play_wav,
    resample,
    resolve_input_device,
    rms,
)
from luxion.voice.stt import SttError, WhisperStt
from luxion.voice.tts import get_tts
from luxion.voice.wake import strip_wake

logger = logging.getLogger(__name__)

VoiceState = Literal["idle", "listening", "transcribing", "speaking"]

#: How long an SSE client waits between keep-alives.
KEEPALIVE_S = 15.0


class VoiceError(RuntimeError):
    """Config, permission or device failure surfaced to the caller."""


# ------------------------------------------------------------------ wire events
class VoiceEvent(BaseModel):
    """One frame on ``/api/voice/events`` (``type`` doubles as the SSE name)."""

    type: Literal["state", "level", "transcript", "wake", "command", "spoken", "error", "ping"]
    #: Latest computed state; only set on ``state`` frames.
    state: VoiceState | None = None
    #: Transcript text (``transcript``) or the wake-stripped command (``command``).
    text: str = ""
    #: Live input level, 0..1 (``level``).
    level: float = 0.0
    #: ``command`` frames are always wake-approved; kept explicit for the UI.
    wake: bool = False
    #: ``spoken`` frames: playback was cut short by barge-in or Stop.
    interrupted: bool = False
    message: str = ""
    at: float = Field(default_factory=time.time)


class VoiceStatus(BaseModel):
    """Everything Settings and the composer need about the voice session."""

    enabled: bool
    state: VoiceState
    listening: bool
    armed: bool
    speaking: bool
    stt: dict[str, Any] = Field(default_factory=dict)
    tts: dict[str, Any] = Field(default_factory=dict)
    wake: dict[str, Any] = Field(default_factory=dict)
    capture: dict[str, Any] = Field(default_factory=dict)
    device: dict[str, Any] | None = None
    devices: list[dict[str, Any]] = Field(default_factory=list)
    microphone: dict[str, Any] = Field(default_factory=dict)
    speaker: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class _Job:
    """A finished utterance handed from the capture loop to the STT worker."""

    __slots__ = ("audio", "future", "mode", "src_rate")

    def __init__(
        self,
        audio: np.ndarray,
        src_rate: int,
        future: Future | None,
        mode: str,
    ) -> None:
        self.audio = audio
        self.src_rate = src_rate
        self.future = future
        self.mode = mode


# ---------------------------------------------------------------------- manager
class VoiceManager:
    """Owns the microphone, the STT worker and the playback thread."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._state_lock = threading.RLock()
        self._sub_lock = threading.Lock()

        self._mode: str = "off"  # off | listen | ptt
        self._armed = False
        self._armed_until = 0.0
        self._last_error: str | None = None

        # capture --------------------------------------------------------
        self._mic: Any = None
        self._capture_thread: threading.Thread | None = None
        self._capture_stop = threading.Event()
        self._blocks: queue.Queue = queue.Queue(maxsize=400)
        self._rate = TARGET_RATE
        self._device_index: int | None = None
        self._device_label = ""
        self._segmenter = Segmenter(
            threshold=settings.voice.vad_threshold,
            min_speech_s=settings.voice.min_speech_s,
            silence_s=settings.voice.silence_s,
        )
        self._pre: list[np.ndarray] = []
        self._pre_len = 0.0
        self._buf: list[np.ndarray] | None = None
        self._utt_len = 0.0
        self._ptt_heard = False
        self._ptt_deadline = 0.0
        self._ptt_future: Future | None = None
        self._barge_run = 0.0

        # speech to text -------------------------------------------------
        self._stt_obj = WhisperStt(
            settings.voice.stt_model,
            device=settings.voice.stt_device,
            compute_type=settings.voice.stt_compute_type,
            language=settings.voice.stt_language,
        )
        self._jobs: queue.Queue = queue.Queue()
        self._stt_thread = threading.Thread(target=self._stt_loop, name="luxion-stt", daemon=True)
        self._stt_thread.start()
        self._stt_depth = 0
        self._warm_thread: threading.Thread | None = None

        # text to speech -------------------------------------------------
        self._speaking = threading.Event()
        self._play_stop: threading.Event | None = None
        self._speech_thread: threading.Thread | None = None

        # level meter ----------------------------------------------------
        self._level = 0.0
        self._last_level_at = 0.0

        # injection points (tests replace these instead of touching hardware)
        self._mic_factory = SoundMic
        self._player = play_wav
        self._tts_factory = get_tts

        self._subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
        self._last_state: VoiceState = "idle"

    # ------------------------------------------------------------ public API
    def status(self) -> VoiceStatus:
        cfg = self.settings.voice
        mic = get_capabilities(self.settings).check("microphone")
        speaker = get_capabilities(self.settings).check("speaker")
        return VoiceStatus(
            enabled=cfg.master,
            state=self.state,
            listening=self._mode == "listen",
            armed=self._armed,
            speaking=self._speaking.is_set(),
            stt={
                "provider": cfg.stt_provider,
                "model": cfg.stt_model,
                "device": cfg.stt_device,
                "compute_type": cfg.stt_compute_type,
                "language": cfg.stt_language or "auto",
                "loaded": self._stt_obj.loaded,
            },
            tts={
                "provider": cfg.tts_provider,
                "enabled": cfg.tts_enabled,
                "rate": cfg.tts_rate,
                "volume": cfg.tts_volume,
            },
            wake={
                "enabled": cfg.wake_enabled,
                "phrase": cfg.wake_phrase,
                "armed_for_s": round(max(0.0, self._armed_until - time.monotonic()), 1)
                if self._armed
                else 0.0,
            },
            capture={
                "device": cfg.mic_device or "default",
                "vad_threshold": cfg.vad_threshold,
                "min_speech_s": cfg.min_speech_s,
                "silence_s": cfg.silence_s,
                "max_utterance_s": cfg.max_utterance_s,
                "barge_in": cfg.barge_in,
                "ptt_timeout_s": cfg.ptt_timeout_s,
                "level": round(self._level, 4),
                "gate": round(self._segmenter.gate, 4),
            },
            device=(
                {"index": self._device_index, "name": self._device_label}
                if self._device_label
                else None
            ),
            devices=self._devices(),
            microphone={"allowed": mic.allowed, "state": mic.state, "reason": mic.reason},
            speaker={
                "allowed": speaker.allowed,
                "state": speaker.state,
                "reason": speaker.reason,
            },
            last_error=self._last_error,
        )

    @property
    def state(self) -> VoiceState:
        if self._speaking.is_set():
            return "speaking"
        if self._stt_depth > 0:
            return "transcribing"
        if self._mode != "off":
            return "listening"
        return "idle"

    def start_listening(self) -> VoiceStatus:
        """Open the microphone and begin wake-word / command capture."""
        self._require_enabled()
        self._require_capability("microphone")
        with self._state_lock:
            if self._mode == "listen":
                return self.status()
            if self._mode == "ptt":
                raise VoiceError("Push-to-talk is already running")
            self._last_error = None
            self._mode = "listen"
            self._start_capture()
        self._warm_stt()
        self._emit_state()
        logger.info("voice_listening_started")
        return self.status()

    def stop_listening(self) -> VoiceStatus:
        """Close the microphone. Safe to call when nothing is running."""
        with self._state_lock:
            mode = self._mode
            self._mode = "off"
            self._armed = False
        self._stop_capture()
        if mode != "off":
            self._emit_state()
            logger.info("voice_listening_stopped", extra={"mode": mode})
        return self.status()

    def recognize(self, timeout_s: float | None = None) -> str:
        """Push-to-talk: capture one utterance and return its transcript.

        The wake word is *not* required here — pressing the button already
        means the user wants Luxion to listen. Returns ``""`` when nothing was
        said (or the budget ran out before any speech started).
        """
        self._require_enabled()
        self._require_capability("microphone")
        timeout = float(timeout_s or self.settings.voice.ptt_timeout_s)
        with self._state_lock:
            if self._mode == "listen":
                raise VoiceError("Voice mode is running — turn it off before push-to-talk")
            if self._mode == "ptt":
                raise VoiceError("Already listening")
            self._last_error = None
            self._mode = "ptt"
            self._ptt_heard = False
            self._ptt_deadline = time.monotonic() + timeout
            future: Future = Future()
            self._ptt_future = future
            self._start_capture()
        self._warm_stt()
        self._emit_state()
        try:
            return str(future.result(timeout=timeout + 60.0))
        except TimeoutError as exc:
            raise VoiceError("Speech recognition timed out") from exc
        finally:
            with self._state_lock:
                self._mode = "off"
                self._ptt_future = None
            self._stop_capture()
            self._emit_state()

    def speak(self, text: str, *, block: bool = True) -> dict[str, Any]:
        """Synthesize ``text`` and play it on the default output.

        ``block=False`` (the API default) returns as soon as the playback
        thread is running; the ``spoken`` event reports when it finished and
        whether it was interrupted.
        """
        self._require_enabled()
        cfg = self.settings.voice
        if not cfg.tts_enabled:
            raise VoiceError("Voice output is turned off in Settings → Voice")
        self._require_capability("speaker")
        if not text.strip():
            raise VoiceError("Nothing to speak")
        if block:
            return {"started": True, "interrupted": self._speak_sync(text)}
        with self._state_lock:
            if self._speech_thread is not None and self._speech_thread.is_alive():
                return {"started": False, "interrupted": False, "reason": "already speaking"}
            thread = threading.Thread(
                target=self._speak_sync, args=(text,), name="luxion-tts", daemon=True
            )
            self._speech_thread = thread
            thread.start()
        return {"started": True, "interrupted": False}

    def stop_speaking(self) -> bool:
        """Interrupt playback (the Stop button, or barge-in from the mic)."""
        stop = self._play_stop
        if stop is None or not self._speaking.is_set():
            return False
        stop.set()
        return True

    def close(self) -> None:
        """Tear the session down — called from the FastAPI lifespan."""
        self.stop_listening()
        self.stop_speaking()
        self._jobs.put(None)
        thread = self._stt_thread
        if thread.is_alive():
            thread.join(timeout=5.0)
        if self._speech_thread is not None:
            self._speech_thread.join(timeout=5.0)
        with self._sub_lock:
            subscribers, self._subscribers = self._subscribers, []
        for stream, loop in subscribers:
            with contextlib.suppress(RuntimeError):  # loop already closed
                loop.call_soon_threadsafe(stream.put_nowait, None)

    # ----------------------------------------------------------- SSE plumbing
    def subscribe(self) -> asyncio.Queue:
        """Register the caller's queue; must run on the event loop."""
        stream: asyncio.Queue = asyncio.Queue(maxsize=256)
        loop = asyncio.get_running_loop()
        with self._sub_lock:
            self._subscribers.append((stream, loop))
        return stream

    def unsubscribe(self, stream: asyncio.Queue) -> None:
        with self._sub_lock:
            self._subscribers = [
                (candidate, loop)
                for candidate, loop in self._subscribers
                if candidate is not stream
            ]

    async def events(self):
        """Async generator consumed by ``sse_stream`` (keep-alive every 15 s)."""
        stream = self.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(stream.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield VoiceEvent(type="ping")
                    continue
                if event is None:
                    return
                yield event
        finally:
            self.unsubscribe(stream)

    def _emit(self, event: VoiceEvent) -> None:
        with self._sub_lock:
            subscribers = list(self._subscribers)
        for stream, loop in subscribers:
            try:
                loop.call_soon_threadsafe(_put, stream, event)
            except RuntimeError:  # the client went away and closed its loop
                logger.debug("voice_event_dropped")

    def _emit_state(self) -> None:
        state = self.state
        if state == self._last_state:
            return
        self._last_state = state
        self._emit(VoiceEvent(type="state", state=state))

    # --------------------------------------------------------------- capture
    def _start_capture(self) -> None:
        """(Re)open the block queue and spawn the capture thread. Lock required."""
        self._blocks = queue.Queue(maxsize=400)
        self._capture_stop = threading.Event()
        self._pre = []
        self._pre_len = 0.0
        self._buf = None
        self._utt_len = 0.0
        self._ptt_heard = False
        self._barge_run = 0.0
        self._segmenter.reset()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="luxion-mic", daemon=True
        )
        self._capture_thread.start()

    def _stop_capture(self) -> None:
        """Close the microphone and wait for the capture loop to exit.

        Never holds ``_state_lock`` across the join — the loop takes that lock
        when it fails, and a lock held over a join is a deadlock waiting to
        happen. When called *from* the loop itself only the stop flag is set;
        the loop's own ``finally`` releases the device.
        """
        with self._state_lock:
            self._capture_stop.set()
            thread = self._capture_thread
        current = threading.current_thread()
        if thread is not None and thread is not current:
            thread.join(timeout=3.0)
        with self._state_lock:
            if self._capture_thread is thread:
                self._capture_thread = None
            if thread is current:
                return
            mic, self._mic = self._mic, None
        if mic is not None:
            mic.stop()

    def _on_block(self, block: np.ndarray) -> None:
        """PortAudio callback — must never block, so drop the oldest on overflow."""
        try:
            self._blocks.put_nowait(block)
        except queue.Full:
            # A stalled consumer drops the oldest frame rather than blocking
            # the PortAudio callback (which must never wait on us).
            with contextlib.suppress(queue.Empty):
                self._blocks.get_nowait()
            with contextlib.suppress(queue.Full):
                self._blocks.put_nowait(block)

    def _on_level(self, level: float) -> None:
        self._level = level
        now = time.monotonic()
        if now - self._last_level_at < 0.1:
            return
        self._last_level_at = now
        self._emit(VoiceEvent(type="level", level=round(level, 4)))

    def _capture_loop(self) -> None:
        stop = self._capture_stop
        mic: Any = None
        try:
            device = self._resolve_device()
            mic = self._mic_factory(
                self._on_block,
                device=device,
                rate=TARGET_RATE,
                on_level=self._on_level,
            )
            mic.start()
        except AudioError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - device drivers raise anything
            self._fail(f"Could not open the microphone: {exc}")
            return
        self._mic = mic
        try:
            self._rate = int(mic.rate)
        except Exception:  # noqa: BLE001 - fake mics may not report a rate
            self._rate = TARGET_RATE
        self._emit_state()
        try:
            while not stop.is_set():
                try:
                    block = self._blocks.get(timeout=0.2)
                except queue.Empty:
                    if self._mode == "ptt" and time.monotonic() >= self._ptt_deadline:
                        self._end_utterance()
                    continue
                if block is None:
                    break
                self._process(block)
                if self._mode == "ptt" and time.monotonic() >= self._ptt_deadline:
                    self._end_utterance()
        finally:
            self._mic = None
            if mic is not None:
                mic.stop()
            self._emit_state()

    def _resolve_device(self) -> int | None:
        spec = self.settings.voice.mic_device
        if not str(spec).strip():
            self._device_index = None
            self._device_label = "System default"
            return None
        index, label = resolve_input_device(spec)
        self._device_index = index
        self._device_label = label
        return index

    def _process(self, block: np.ndarray) -> None:
        cfg = self.settings.voice
        rate = self._rate or TARGET_RATE
        dt = block.size / float(rate)
        level = rms(block)
        self._level = level

        if self._speaking.is_set() and cfg.barge_in:
            gate = max(0.15, self._segmenter.gate * 4.0)
            if level >= gate:
                self._barge_run += dt
                if self._barge_run >= max(cfg.min_speech_s, 0.25):
                    self._barge_run = 0.0
                    logger.info("voice_barge_in")
                    self.stop_speaking()
            else:
                self._barge_run = 0.0

        if self._mode == "ptt":
            self._feed_ptt(block, level, dt, rate)
        elif self._mode == "listen":
            self._feed_listen(block, level, dt, rate)

    def _feed_listen(self, block: np.ndarray, level: float, dt: float, rate: int) -> None:
        """Energy VAD with a rolling pre-roll so the first syllable survives."""
        cfg = self.settings.voice
        self._pre.append(block)
        self._pre_len += dt
        while self._pre_len > cfg.min_speech_s and len(self._pre) > 1:
            first = self._pre.pop(0)
            self._pre_len -= first.size / float(rate)

        event = self._segmenter.feed(level, dt)
        if event == "start":
            self._buf = list(self._pre)
            self._utt_len = self._pre_len
            return
        if event == "end":
            if self._buf is not None:
                self._buf.append(block)
                self._end_utterance()
            return
        if self._buf is not None:
            self._buf.append(block)
            self._utt_len += dt
            if self._utt_len >= cfg.max_utterance_s:
                self._end_utterance()
                self._segmenter.reset()

    def _feed_ptt(self, block: np.ndarray, level: float, dt: float, rate: int) -> None:
        """Push-to-talk: roll a buffer from the first block, stop on silence."""
        if self._buf is None:
            self._buf = []
            self._utt_len = 0.0
        self._buf.append(block)
        self._utt_len += dt

        event = self._segmenter.feed(level, dt)
        if event == "start":
            self._ptt_heard = True
            return
        if event == "end" and self._ptt_heard:
            self._end_utterance()
            return
        if self._utt_len >= self.settings.voice.max_utterance_s:
            self._end_utterance()

    def _end_utterance(self) -> None:
        """Hand the accumulated audio to the STT worker (never blocks)."""
        buf, self._buf = self._buf, None
        if buf is None:
            return  # already consumed (the deadline path retries every tick)
        self._utt_len = 0.0
        mode = self._mode
        future = self._ptt_future if mode == "ptt" else None
        if mode == "ptt":
            self._stop_capture()
            if not self._ptt_heard:
                # Nothing ever crossed the gate: answer immediately instead of
                # spending a model load on room tone.
                if future is not None and not future.done():
                    future.set_result("")
                return
        if not buf:
            return
        with self._state_lock:
            self._stt_depth += 1
        self._emit_state()
        self._jobs.put(_Job(np.concatenate(buf), self._rate, future, mode))

    # ----------------------------------------------------------- STT worker
    def _stt_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            text = ""
            error: str | None = None
            try:
                if job.audio.size:
                    audio = resample(job.audio, job.src_rate, TARGET_RATE)
                    text = self._stt_obj.transcribe(audio)
            except SttError as exc:
                error = str(exc)
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                error = f"Speech recognition failed: {exc}"
            finally:
                with self._state_lock:
                    self._stt_depth = max(0, self._stt_depth - 1)
                self._emit_state()
            self._on_result(text, error, job)

    def _on_result(self, text: str, error: str | None, job: _Job) -> None:
        if error:
            self._last_error = error
            self._emit(VoiceEvent(type="error", message=error))
        if job.mode == "ptt":
            future = job.future
            if future is not None and not future.done():
                if error and not text:
                    future.set_exception(VoiceError(error))
                else:
                    future.set_result(text)
            self._emit(VoiceEvent(type="transcript", text=text))
            return

        self._emit(VoiceEvent(type="transcript", text=text))
        if error or not text.strip():
            return
        self._publish_command(text)

    def _publish_command(self, text: str) -> None:
        """Wake-word gate for the continuous session (PRD §26)."""
        cfg = self.settings.voice
        if not cfg.wake_enabled:
            self._emit(VoiceEvent(type="command", text=text, wake=True))
            return
        if self._armed and time.monotonic() >= self._armed_until:
            self._armed = False
        if not self._armed:
            rest = strip_wake(text, cfg.wake_phrase)
            if rest is None:
                logger.debug("voice_ignored_no_wake")
                return
            if rest == "":
                self._armed = True
                self._armed_until = time.monotonic() + cfg.wake_arm_s
                self._emit(VoiceEvent(type="wake", text=cfg.wake_phrase))
                return
            self._emit(VoiceEvent(type="command", text=rest, wake=True))
            return
        rest = strip_wake(text, cfg.wake_phrase)
        self._armed = False
        self._emit(VoiceEvent(type="command", text=rest if rest is not None else text, wake=True))

    def _warm_stt(self) -> None:
        if self._stt_obj.loaded:
            return
        thread = self._warm_thread
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=self._warm_stt_body, name="luxion-stt-warm", daemon=True)
        self._warm_thread = thread
        thread.start()

    def _warm_stt_body(self) -> None:
        try:
            self._stt_obj.load()
        except SttError as exc:
            self._last_error = str(exc)
            self._emit(VoiceEvent(type="error", message=str(exc)))

    # --------------------------------------------------------------- playback
    def _speak_sync(self, text: str) -> bool:
        """Synthesize + play on this thread; returns whether it was cut short."""
        cfg = self.settings.voice
        stop = threading.Event()
        interrupted = False
        with self._state_lock:
            self._play_stop = stop
        self._speaking.set()
        self._barge_run = 0.0
        self._emit_state()
        try:
            provider = self._tts_factory(cfg.tts_provider, voice=cfg)
            data = provider.synthesize(text, rate=cfg.tts_rate, volume=cfg.tts_volume)
            completed = self._player(data, stop)
            interrupted = not completed
        except Exception as exc:  # noqa: BLE001 - the reply still shows as text
            self._last_error = str(exc)
            logger.warning("voice_speak_failed error=%s", exc)
            self._emit(VoiceEvent(type="error", message=str(exc)))
        finally:
            self._speaking.clear()
            with self._state_lock:
                self._play_stop = None
            self._emit_state()
        self._emit(VoiceEvent(type="spoken", interrupted=interrupted))
        return interrupted

    # ---------------------------------------------------------------- helpers
    def _fail(self, message: str) -> None:
        self._last_error = message
        with self._state_lock:
            self._mode = "off"
            future, self._ptt_future = self._ptt_future, None
        if future is not None and not future.done():
            future.set_exception(VoiceError(message))
        self._emit(VoiceEvent(type="error", message=message))
        self._emit_state()
        logger.warning("voice_capture_failed error=%s", message)

    def _require_enabled(self) -> None:
        if not self.settings.voice.master:
            raise VoiceError("Voice is turned off in Settings → Voice")

    def _require_capability(self, capability_id: str) -> None:
        decision = get_capabilities(self.settings).check(capability_id)
        if not decision.allowed:
            raise VoiceError(decision.reason)

    def _devices(self) -> list[dict[str, Any]]:
        try:
            return list_input_devices()
        except AudioError:
            return []


def _put(stream: asyncio.Queue, event: VoiceEvent) -> None:
    # A stalled client drops frames rather than blocking the manager.
    with contextlib.suppress(asyncio.QueueFull):
        stream.put_nowait(event)


_manager: VoiceManager | None = None
_manager_key: tuple | None = None


def get_voice_manager(settings: Settings | None = None) -> VoiceManager:
    """Process-wide manager, rebuilt when the data directory changes."""
    global _manager, _manager_key
    resolved = settings or get_settings()
    key = (str(resolved.app.data_dir),)
    if _manager is None or _manager_key != key:
        if _manager is not None:
            _manager.close()
        _manager = VoiceManager(resolved)
        _manager_key = key
    return _manager


def reset_voice_manager() -> None:
    """Drop the cached manager (tests and Settings → voice config changes)."""
    close_voice_manager()


def close_voice_manager() -> None:
    """Shut a running manager down without constructing one first."""
    global _manager, _manager_key
    if _manager is not None:
        _manager.close()
    _manager = None
    _manager_key = None
