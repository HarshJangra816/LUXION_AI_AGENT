"""Voice system (PRD §26, §5.5, §5.6, Phase 4).

``audio``   microphone capture, energy VAD and interruptible playback
``stt``     faster-whisper recognizer (downloaded once, then cached)
``tts``     provider abstraction; Windows SAPI5 ships first
``wake``    wake-phrase matching for the continuous session
``manager`` the session itself — what ``/api/voice`` exposes
"""

from luxion.voice.audio import TARGET_RATE, AudioError, Segmenter
from luxion.voice.manager import (
    VoiceError,
    VoiceEvent,
    VoiceManager,
    VoiceStatus,
    get_voice_manager,
    reset_voice_manager,
)
from luxion.voice.stt import SttError, WhisperStt
from luxion.voice.tts import TtsError, get_tts

__all__ = [
    "TARGET_RATE",
    "AudioError",
    "Segmenter",
    "SttError",
    "TtsError",
    "VoiceError",
    "VoiceEvent",
    "VoiceManager",
    "VoiceStatus",
    "WhisperStt",
    "get_tts",
    "get_voice_manager",
    "reset_voice_manager",
]
