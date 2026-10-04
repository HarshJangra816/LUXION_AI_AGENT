"""Phase 4: the voice pipeline (PRD §26, §5.5, §5.6) — no hardware required.

Everything that touches a device is injected: a scripted fake microphone feeds
blocks into the real capture loop, a fake STT answers with canned text and a
fake player stands in for the speaker, so the segmenter, the wake gate, the
push-to-talk future, barge-in and the capability hard-blocks are all exercised
exactly as they run in production.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

import numpy as np
import pytest

from luxion.config.settings import (
    Settings,
    apply_voice_overrides,
    save_voice_overrides,
)
from luxion.config.voice_override import load_overrides
from luxion.security.capabilities import CapabilityDecision
from luxion.voice import manager as manager_module
from luxion.voice.audio import TARGET_RATE, Segmenter, rms
from luxion.voice.manager import VoiceError, VoiceManager
from luxion.voice.wake import normalize, strip_wake

#: 16 kHz mono block of 0.1 s — the segmenter's clock comes from block sizes,
#: so a scripted capture runs faster than real time and stays deterministic.
BLOCK = 1600
LOUD = np.full(BLOCK, 0.25, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)

#: Utterance shape used by the scripted-capture tests: 5 blocks of speech
#: (0.5 s ≥ min_speech_s) followed by 6 of silence (0.6 s ≥ silence_s).
UTTERANCE = [LOUD] * 5 + [QUIET] * 6


# --------------------------------------------------------------------- fakes
class FakeStt:
    """Canned answers for the STT worker (never loads a model)."""

    def __init__(self, answers: Iterable[str] = ("hello there",)) -> None:
        self.answers = list(answers)
        self.loaded = True
        self.calls = 0

    def load(self) -> None:
        self.loaded = True

    def transcribe(self, audio: np.ndarray) -> str:
        self.calls += 1
        if not self.answers:
            return ""
        return self.answers.pop(0)


class FakeMic:
    """Pushes a scripted block sequence into the manager's capture queue."""

    def __init__(
        self,
        sink: Callable[[np.ndarray], None],
        *,
        script: list[np.ndarray] | None = None,
        rate: int = TARGET_RATE,
        on_level: Callable[[float], None] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._sink = sink
        self._script = script if script is not None else []
        self._rate = rate
        self._on_level = on_level
        self._delay = delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def rate(self) -> int:
        return self._rate

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        for block in self._script:
            if self._stop.is_set():
                return
            if self._on_level is not None:
                self._on_level(rms(block))
            self._sink(block)
            if self._delay:
                time.sleep(self._delay)


class FakeTts:
    """Text-to-speech stub — the player is replaced, so the bytes are ignored."""

    def __init__(self, provider: str = "windows") -> None:
        self.provider = provider
        self.spoken: list[str] = []

    def synthesize(self, text: str, *, rate: int = 0, volume: int = 100) -> bytes:
        self.spoken.append(text)
        return b"RIFF-fake-wav"


class AllowCaps:
    """Capability store stand-in: every gate is granted."""

    def check(self, capability_id: str) -> CapabilityDecision:
        return CapabilityDecision(
            capability=capability_id,
            state="granted",
            allowed=True,
            reason="allowed for the test",
        )


class DenyCaps:
    """Capability store stand-in: every gate refuses."""

    def check(self, capability_id: str) -> CapabilityDecision:
        return CapabilityDecision(
            capability=capability_id,
            state="denied",
            allowed=False,
            reason=f"{capability_id} is turned off",
        )


def mic_factory(script: list[np.ndarray], delay: float = 0.0):
    """Build the ``_mic_factory`` seam with a script baked in."""

    def build(
        sink: Callable[[np.ndarray], None],
        *,
        device: int | None = None,
        rate: int = TARGET_RATE,
        on_level: Callable[[float], None] | None = None,
    ) -> FakeMic:
        return FakeMic(sink, script=script, rate=rate, on_level=on_level, delay=delay)

    return build


def wait_for(predicate: Callable[[], bool], message: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {message}")


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def settings(tmp_path) -> Settings:
    """Fast voice policy: small VAD windows so a script finishes quickly."""
    return Settings(
        app={"data_dir": str(tmp_path)},
        voice={
            "min_speech_s": 0.2,
            "silence_s": 0.4,
            # `max_utterance_s` may not go below 3 s (VoiceConfig constraint).
            "max_utterance_s": 3.0,
            "ptt_timeout_s": 5.0,
        },
    )


@pytest.fixture
def manager(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> VoiceManager:
    monkeypatch.setattr(manager_module, "get_capabilities", lambda *_a, **_k: AllowCaps())
    session = VoiceManager(settings)
    session._stt_obj = FakeStt()
    yield session
    session.close()


@pytest.fixture
def events(manager: VoiceManager, monkeypatch: pytest.MonkeyPatch) -> list:
    """Every frame the manager emits, captured in order."""
    seen: list = []
    monkeypatch.setattr(manager, "_emit", seen.append)
    return seen


def types_of(frames: Iterable) -> list[str]:
    return [frame.type for frame in frames]


# ----------------------------------------------------------------- segmenter
def test_segmenter_opens_and_closes_an_utterance() -> None:
    segmenter = Segmenter(threshold=0.01, min_speech_s=0.2, silence_s=0.4)
    assert segmenter.gate >= 0.01
    assert segmenter.feed(0.2, 0.1) is None  # 0.1 s of speech is not enough yet
    assert segmenter.feed(0.2, 0.1) == "start"
    assert segmenter.active is True
    for index in range(3):  # 0.4 s of quiet closes the utterance
        assert segmenter.feed(0.0, 0.1) is None, index
    assert segmenter.feed(0.0, 0.1) == "end"
    assert segmenter.active is False


def test_segmenter_gate_follows_the_learned_noise_floor() -> None:
    segmenter = Segmenter(threshold=0.01, min_speech_s=0.2, silence_s=0.4)
    for _ in range(40):
        # steady ambience sits under the gate, so the floor tracks it upward
        assert segmenter.feed(0.02, 0.1) is None
    assert segmenter.noise_floor > 0.015
    assert segmenter.gate >= segmenter.noise_floor * 2.5
    assert segmenter.active is False


def test_segmenter_reset_keeps_the_learned_floor() -> None:
    segmenter = Segmenter(threshold=0.01, min_speech_s=0.2, silence_s=0.4)
    for _ in range(40):
        segmenter.feed(0.02, 0.1)
    floor = segmenter.noise_floor
    segmenter.reset()
    assert segmenter.active is False
    assert segmenter.noise_floor == floor


# ---------------------------------------------------------------- wake word
def test_strip_wake_variants() -> None:
    assert strip_wake("hey luxion", "hey luxion") == ""
    assert strip_wake("Hey Luxion, open chrome.", "hey luxion") == "open chrome."
    assert strip_wake("open chrome", "hey luxion") is None
    assert strip_wake("", "hey luxion") is None
    assert strip_wake("hey-luxion open chrome", "hey luxion") == "open chrome"
    assert normalize("Hey, Luxion!") == "hey luxion"


def test_bare_wake_phrase_arms_the_session(manager, events) -> None:
    manager._publish_command("hey luxion")
    assert types_of(events) == ["wake"]
    assert events[0].text == "hey luxion"
    assert manager._armed is True


def test_wake_phrase_then_command_runs_in_one_utterance(manager, events) -> None:
    manager._publish_command("Hey Luxion, open chrome")
    assert types_of(events) == ["command"]
    assert events[0].text == "open chrome"
    assert events[0].wake is True
    assert manager._armed is False


def test_armed_session_takes_the_next_utterance_verbatim(manager, events) -> None:
    manager._publish_command("hey luxion")
    manager._publish_command("what time is it")
    assert types_of(events) == ["wake", "command"]
    assert events[1].text == "what time is it"
    assert manager._armed is False, "the arm is consumed by one command"


def test_utterance_without_the_wake_phrase_is_ignored(manager, events) -> None:
    manager._publish_command("tell me a joke")
    assert events == []
    assert manager._armed is False


def test_expired_arm_requires_the_phrase_again(manager, events) -> None:
    manager._armed = True
    manager._armed_until = time.monotonic() - 1.0
    manager._publish_command("open chrome")
    assert events == []
    assert manager._armed is False


def test_wake_disabled_publishes_every_command(manager, events, settings) -> None:
    settings.voice.wake_enabled = False
    manager._publish_command("open chrome")
    assert types_of(events) == ["command"]
    assert events[0].text == "open chrome"
    assert events[0].wake is True


def test_nested_wake_phrase_keeps_its_casing(manager, events) -> None:
    manager._publish_command("hey luxion What's the weather?")
    assert events[0].text == "What's the weather?"


# ------------------------------------------------------------ capability gate
def _deny_all(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(manager_module, "get_capabilities", lambda *_a, **_k: DenyCaps())


def test_microphone_capability_blocks_listening(settings, monkeypatch) -> None:
    _deny_all(monkeypatch, settings)
    session = VoiceManager(settings)
    session._stt_obj = FakeStt()
    try:
        with pytest.raises(VoiceError, match="microphone is turned off"):
            session.start_listening()
        assert session._mic is None
        assert session.status().listening is False
    finally:
        session.close()


def test_microphone_capability_blocks_push_to_talk(settings, monkeypatch) -> None:
    _deny_all(monkeypatch, settings)
    session = VoiceManager(settings)
    session._stt_obj = FakeStt()
    try:
        with pytest.raises(VoiceError, match="microphone is turned off"):
            session.recognize()
    finally:
        session.close()


def test_speaker_capability_blocks_playback(settings, monkeypatch) -> None:
    _deny_all(monkeypatch, settings)
    session = VoiceManager(settings)
    session._stt_obj = FakeStt()
    try:
        with pytest.raises(VoiceError, match="speaker is turned off"):
            session.speak("hello", block=True)
    finally:
        session.close()


def test_master_switch_blocks_every_entry_point(manager) -> None:
    manager.settings.voice.master = False
    with pytest.raises(VoiceError, match="turned off in Settings"):
        manager.start_listening()
    with pytest.raises(VoiceError, match="turned off in Settings"):
        manager.recognize()
    with pytest.raises(VoiceError, match="turned off in Settings"):
        manager.speak("hello", block=True)


# ------------------------------------------------------------------ push to talk
def test_push_to_talk_returns_the_transcript(manager, events) -> None:
    manager._stt_obj = FakeStt(["open chrome"])
    manager._mic_factory = mic_factory(list(UTTERANCE))

    text = manager.recognize(timeout_s=5.0)

    assert text == "open chrome"
    assert "transcript" in types_of(events)
    assert manager.status().state == "idle", "the session is closed again"


def test_push_to_talk_answers_empty_when_nothing_was_said(manager) -> None:
    manager._stt_obj = FakeStt(["never used"])
    # 3.5 s of room tone exceeds voice.max_utterance_s without crossing the gate
    manager._mic_factory = mic_factory([QUIET] * 35)

    assert manager.recognize(timeout_s=5.0) == ""


def test_push_to_talk_rejects_a_second_session(manager) -> None:
    manager._mode = "listen"
    with pytest.raises(VoiceError, match="turn it off before push-to-talk"):
        manager.recognize()


# ------------------------------------------------------------------- listening
def test_listen_wakes_and_publishes_the_command(manager, events) -> None:
    manager._stt_obj = FakeStt(["hey luxion", "open chrome"])
    script = [*UTTERANCE, *UTTERANCE]
    manager._mic_factory = mic_factory(script)

    manager.start_listening()
    try:
        assert manager.status().listening is True
        wait_for(lambda: "command" in types_of(events), "the wake-gated command")
        commands = [frame for frame in events if frame.type == "command"]
        assert commands[0].text == "open chrome"
        assert commands[0].wake is True
        assert "wake" in types_of(events)
        assert "transcript" in types_of(events)
    finally:
        manager.stop_listening()
    assert manager.status().listening is False
    assert manager.status().state == "idle"


def test_stop_listening_is_idempotent(manager) -> None:
    manager.stop_listening()
    manager.stop_listening()
    assert manager.status().listening is False
    assert manager.status().state == "idle"


def test_second_utterance_is_ignored_without_the_phrase(manager, events) -> None:
    manager._stt_obj = FakeStt(["hello there"])
    manager._mic_factory = mic_factory(list(UTTERANCE))

    manager.start_listening()
    try:
        wait_for(lambda: "transcript" in types_of(events), "the transcript")
        time.sleep(0.2)
        assert "command" not in types_of(events)
    finally:
        manager.stop_listening()


# -------------------------------------------------------------------- barge in
def test_talking_over_a_reply_cuts_playback(manager) -> None:
    stop = threading.Event()
    manager._play_stop = stop
    manager._speaking.set()
    manager._mode = "listen"

    for _ in range(5):  # 0.5 s above the barge-in gate
        manager._process(LOUD)

    assert stop.is_set(), "sustained speech must interrupt the reply"


def test_barge_in_ignores_a_momentary_click(manager) -> None:
    stop = threading.Event()
    manager._play_stop = stop
    manager._speaking.set()
    manager._mode = "listen"

    manager._process(LOUD)
    manager._process(QUIET)

    assert not stop.is_set()


# ------------------------------------------------------------------- playback
def test_speak_reports_a_completed_playback(manager, events) -> None:
    tts = FakeTts()
    manager._tts_factory = lambda provider, **_kwargs: tts
    manager._player = lambda data, stop: True

    result = manager.speak("hello world", block=True)

    assert result == {"started": True, "interrupted": False}
    assert tts.spoken == ["hello world"]
    spoken = [frame for frame in events if frame.type == "spoken"]
    assert len(spoken) == 1 and spoken[0].interrupted is False


def test_speak_reports_an_interrupted_playback(manager, events) -> None:
    manager._tts_factory = lambda provider, **_kwargs: FakeTts()
    manager._player = lambda data, stop: False

    result = manager.speak("hello world", block=True)

    assert result["interrupted"] is True
    spoken = [frame for frame in events if frame.type == "spoken"]
    assert spoken[0].interrupted is True


def test_speak_rejects_blank_text_and_disabled_output(manager) -> None:
    manager._tts_factory = lambda provider, **_kwargs: FakeTts()
    manager._player = lambda data, stop: True
    with pytest.raises(VoiceError, match="Nothing to speak"):
        manager.speak("   ", block=True)
    manager.settings.voice.tts_enabled = False
    with pytest.raises(VoiceError, match="Voice output is turned off"):
        manager.speak("hello", block=True)


def test_stop_speaking_is_safe_when_idle(manager) -> None:
    assert manager.stop_speaking() is False


# --------------------------------------------------------------------- status
def test_status_exposes_everything_the_ui_needs(manager) -> None:
    payload = manager.status().model_dump()

    assert payload["enabled"] is True
    assert payload["state"] == "idle"
    assert payload["listening"] is False
    assert payload["speaking"] is False
    assert payload["stt"]["model"] == "base.en"
    assert payload["tts"]["enabled"] is True
    assert payload["wake"]["phrase"] == "hey luxion"
    assert payload["capture"]["ptt_timeout_s"] == 5.0
    assert payload["capture"]["barge_in"] is True
    assert set(payload["microphone"]) == {"allowed", "state", "reason"}
    assert set(payload["speaker"]) == {"allowed", "state", "reason"}
    assert payload["last_error"] is None


def test_state_events_follow_the_session(manager, events) -> None:
    manager._stt_obj = FakeStt()
    manager._mic_factory = mic_factory(list(UTTERANCE))

    manager.start_listening()
    states = [frame.state for frame in events if frame.type == "state"]
    assert "listening" in states
    manager.stop_listening()
    # the level ticker can land one more frame after the transition
    states = [frame.state for frame in events if frame.type == "state"]
    assert states[-1] == "idle"


# --------------------------------------------------------------- config overlay
def test_voice_overlay_merges_one_knob_at_a_time(tmp_path) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)})

    save_voice_overrides(settings, {"tts_rate": 30})
    save_voice_overrides(settings, {"wake_phrase": "computer"})

    assert load_overrides(tmp_path) == {"tts_rate": 30, "wake_phrase": "computer"}

    fresh = Settings(app={"data_dir": str(tmp_path)})
    apply_voice_overrides(fresh)
    assert fresh.voice.tts_rate == 30
    assert fresh.voice.wake_phrase == "computer"


def test_voice_overlay_drops_values_the_model_rejects(tmp_path) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)})

    save_voice_overrides(settings, {"tts_rate": 30})
    save_voice_overrides(settings, {"tts_rate": 9999, "wake_phrase": "computer"})

    assert load_overrides(tmp_path) == {"tts_rate": 30, "wake_phrase": "computer"}

    fresh = Settings(app={"data_dir": str(tmp_path)})
    apply_voice_overrides(fresh)
    assert fresh.voice.tts_rate == 30


def test_voice_overlay_ignores_unknown_knobs(tmp_path) -> None:
    settings = Settings(app={"data_dir": str(tmp_path)})
    save_voice_overrides(settings, {"not_a_voice_knob": 1, "wake_arm_s": 30})

    assert load_overrides(tmp_path) == {"wake_arm_s": 30}
