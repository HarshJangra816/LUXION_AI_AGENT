"""Voice control surface (PRD §26, §32 Settings → Voice, Phase 4).

``GET    /api/voice``           live status: state, devices, STT/TTS/wake config
``POST   /api/voice/listen``    ``{on}`` — open/close the microphone session
``POST   /api/voice/recognize`` push-to-talk: one utterance → its transcript
``POST   /api/voice/speak``     ``{text}`` — synthesize and play a reply
``POST   /api/voice/stop``      interrupt whatever is playing
``GET    /api/voice/events``    SSE: state / level / transcript / wake /
                                command / spoken / error
``GET    /api/voice/config``    effective settings + built-in defaults
``PUT    /api/voice/config``    persist the Settings → Voice edits
``DELETE /api/voice/config``    back to ``.env`` defaults
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from luxion.api.sse import STREAM_HEADERS, sse_stream
from luxion.config.settings import (
    VoiceConfig,
    get_settings,
    reset_settings_cache,
    save_voice_overrides,
)
from luxion.config.voice_override import clear_overrides
from luxion.voice.manager import VoiceError, VoiceStatus, get_voice_manager, reset_voice_manager

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceConfigBundle(BaseModel):
    """What Settings → Voice edits (effective values + built-in defaults)."""

    config: VoiceConfig
    defaults: VoiceConfig


class ListenBody(BaseModel):
    on: bool = True


class RecognizeBody(BaseModel):
    #: Capture budget in seconds; omitted = ``voice.ptt_timeout_s``.
    timeout_s: float | None = Field(default=None, ge=1.0, le=120.0)


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    #: ``false`` returns immediately and reports progress on the event stream.
    block: bool = False


class VoiceConfigPatch(BaseModel):
    """Partial voice settings — mirrors every field of ``VoiceConfig``.

    All fields optional so the Settings card can PATCH just what changed; a
    test keeps this in sync with :class:`luxion.config.settings.VoiceConfig`
    so a new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    master: bool | None = None
    stt_provider: str | None = None
    stt_model: str | None = None
    stt_device: str | None = None
    stt_compute_type: str | None = None
    stt_language: str | None = None
    tts_provider: str | None = None
    tts_enabled: bool | None = None
    tts_rate: int | None = None
    tts_volume: int | None = None
    tts_model: str | None = None
    tts_instruct: str | None = None
    tts_steps: int | None = None
    tts_language: str | None = None
    wake_enabled: bool | None = None
    wake_phrase: str | None = None
    wake_arm_s: float | None = None
    mic_device: str | None = None
    vad_threshold: float | None = None
    min_speech_s: float | None = None
    silence_s: float | None = None
    max_utterance_s: float | None = None
    barge_in: bool | None = None
    ptt_timeout_s: float | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


def _guard(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=VoiceStatus)
def voice_status() -> VoiceStatus:
    """Everything the composer and Settings → Voice need right now."""
    return get_voice_manager().status()


@router.post("/listen", response_model=VoiceStatus)
def set_listening(body: ListenBody) -> VoiceStatus:
    """Open (``on=true``) or close the continuous microphone session."""
    manager = get_voice_manager()
    if body.on:
        return _guard(manager.start_listening)
    return manager.stop_listening()


@router.post("/recognize")
def recognize(body: RecognizeBody | None = None) -> dict[str, str]:
    """Push-to-talk: capture one utterance and return its transcript.

    Blocks for at most ``timeout_s`` (or ``voice.ptt_timeout_s``); an empty
    string means nothing crossed the speech gate.
    """
    timeout = body.timeout_s if body else None
    text = _guard(get_voice_manager().recognize, timeout)
    return {"text": text}


@router.post("/speak")
def speak(body: SpeakBody) -> dict[str, Any]:
    """Synthesize ``text`` and play it on the default output device."""
    return _guard(get_voice_manager().speak, body.text, block=body.block)


@router.post("/stop")
def stop_speech() -> dict[str, Any]:
    """Interrupt current playback (the composer's Stop button)."""
    return {"stopped": get_voice_manager().stop_speaking()}


@router.get("/events")
async def voice_events() -> StreamingResponse:
    """Server-sent voice events: state, level, transcript, wake, command…"""
    return StreamingResponse(
        sse_stream(get_voice_manager().events()),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@router.get("/config", response_model=VoiceConfigBundle)
def read_config() -> VoiceConfigBundle:
    """Effective voice settings (defaults → `.env` → `voice.json`) + defaults."""
    return VoiceConfigBundle(config=get_settings().voice, defaults=VoiceConfig())


@router.put("/config", response_model=VoiceStatus)
def update_config(body: VoiceConfigPatch) -> VoiceStatus:
    """Persist the Settings → Voice edits and rebuild the session."""
    values = body.values()
    if not values:
        raise HTTPException(status_code=400, detail="No voice settings were provided")
    save_voice_overrides(get_settings(), values)
    return _rebuild()


@router.delete("/config", response_model=VoiceStatus)
def reset_config() -> VoiceStatus:
    """Drop ``voice.json`` so ``.env`` / built-in defaults win again."""
    clear_overrides(get_settings().app.data_dir)
    reset_settings_cache()
    return _rebuild()


def _rebuild() -> VoiceStatus:
    """Restart the session so the freshly persisted settings take effect."""
    manager = get_voice_manager()
    if manager.status().listening:
        manager.stop_listening()
    reset_voice_manager()
    return get_voice_manager().status()


__all__ = [
    "ListenBody",
    "RecognizeBody",
    "SpeakBody",
    "VoiceConfigBundle",
    "VoiceConfigPatch",
    "router",
]
