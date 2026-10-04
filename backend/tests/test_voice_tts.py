"""TTS provider switchboard (PRD 5.6) - Windows SAPI5 and OmniVoice.

The OmniVoice model is stubbed out through ``sys.modules`` so these tests
never download weights or run diffusion steps; what they pin down is the
contract Luxion relies on: WAV bytes back, the voice design prompt and step
count forwarded, ``tts_rate`` mapped onto OmniVoice's own speed factor, and
every failure turned into a :class:`TtsError` instead of a crash.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from luxion.config.settings import Settings
from luxion.voice.tts import (
    OmniVoiceTts,
    TtsError,
    WindowsTts,
    get_tts,
    reset_tts_cache,
    speechify,
)


@pytest.fixture(autouse=True)
def clean_tts_cache():
    reset_tts_cache()
    yield
    reset_tts_cache()


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    import io

    import soundfile as sf

    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    return np.atleast_1d(audio), int(rate)


@pytest.fixture
def fake_omnivoice(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install a stand-in ``omnivoice`` package that records every call."""

    class FakeOmniVoice:
        sampling_rate = 24_000
        load_calls: list[tuple[str, str | None]] = []
        generate_calls: list[dict] = []
        amplitude = 0.5
        error: Exception | None = None

        @classmethod
        def from_pretrained(cls, name: str, *, device_map: str | None = None):
            cls.load_calls.append((name, device_map))
            if cls.error is not None:
                raise cls.error
            return cls()

        def generate(self, **kwargs):
            FakeOmniVoice.generate_calls.append(kwargs)
            if FakeOmniVoice.error is not None:
                raise FakeOmniVoice.error
            samples = int(24_000 * 0.05)
            return [np.full(samples, FakeOmniVoice.amplitude, dtype=np.float32)]

    package = SimpleNamespace(OmniVoice=FakeOmniVoice)
    monkeypatch.setitem(sys.modules, "omnivoice", package)
    return SimpleNamespace(cls=FakeOmniVoice, package=package)


# ---------------------------------------------------------------- switchboard
def test_switchboard_resolves_both_providers() -> None:
    assert isinstance(get_tts("windows"), WindowsTts)
    assert isinstance(get_tts("omnivoice"), OmniVoiceTts)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(TtsError, match="Unknown TTS provider"):
        get_tts("piper")


def test_omnivoice_provider_is_cached_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_tts("omnivoice")
    second = get_tts("omnivoice")
    assert first is second

    other = get_tts("omnivoice", voice=Settings().voice.model_copy(update={"tts_model": "local"}))
    assert other is not first
    assert other.model_name == "local"


def test_knobs_follow_the_voice_config(fake_omnivoice) -> None:
    voice = Settings().voice.model_copy(
        update={
            "tts_instruct": "male, british accent",
            "tts_steps": 32,
            "tts_language": "English",
        }
    )

    provider = get_tts("omnivoice", voice=voice)

    assert provider.instruct == "male, british accent"
    assert provider.steps == 32
    assert provider.language == "English"
    # changing the prompt must not reload the weights
    before = len(fake_omnivoice.cls.load_calls)
    voice.tts_steps = 8
    assert get_tts("omnivoice", voice=voice) is provider
    assert provider.steps == 8
    assert len(fake_omnivoice.cls.load_calls) == before


# ------------------------------------------------------------------ synthesis
def test_synthesis_returns_playable_wav_with_the_configured_voice(fake_omnivoice) -> None:
    provider = OmniVoiceTts("k2-fsa/OmniVoice", instruct="female, moderate pitch", steps=16)

    data = provider.synthesize("Hello there.", rate=0, volume=100)

    audio, rate = decode_wav(data)
    assert rate == 24_000
    assert audio.size > 0
    assert float(np.max(np.abs(audio))) == pytest.approx(0.5, abs=0.01)
    assert fake_omnivoice.cls.load_calls == [("k2-fsa/OmniVoice", "cpu")]
    call = fake_omnivoice.cls.generate_calls[0]
    assert call["text"] == "Hello there."
    assert call["instruct"] == "female, moderate pitch"
    assert call["num_step"] == 16
    assert call["speed"] == 1.0
    assert call["language"] is None


def test_rate_maps_onto_the_model_speed_factor(fake_omnivoice) -> None:
    provider = OmniVoiceTts()

    provider.synthesize("One.", rate=100)
    provider.synthesize("Two.", rate=-50)
    provider.synthesize("Three.", rate=500)  # clamped

    speeds = [call["speed"] for call in fake_omnivoice.cls.generate_calls]
    assert speeds == [2.0, 0.5, 2.0]


def test_volume_scales_the_samples(fake_omnivoice) -> None:
    provider = OmniVoiceTts()

    loud, _ = decode_wav(provider.synthesize("Hello", volume=100))
    quiet, _ = decode_wav(provider.synthesize("Hello", volume=40))

    # tolerance covers 16-bit PCM rounding of the scaled samples
    assert float(np.max(np.abs(quiet))) == pytest.approx(
        float(np.max(np.abs(loud))) * 0.4, rel=0.01
    )


def test_blank_text_never_reaches_the_model(fake_omnivoice) -> None:
    provider = OmniVoiceTts()

    with pytest.raises(TtsError, match="Nothing to speak"):
        provider.synthesize("   ")
    with pytest.raises(TtsError, match="Nothing to speak"):
        provider.synthesize("**   **")

    assert fake_omnivoice.cls.generate_calls == []


def test_markdown_is_flattened_before_synthesis(fake_omnivoice) -> None:
    provider = OmniVoiceTts()

    provider.synthesize("**Bold** and `code`")

    assert fake_omnivoice.cls.generate_calls[0]["text"] == "Bold and code"


# --------------------------------------------------------------- failure paths
def test_model_load_failure_becomes_a_tts_error(fake_omnivoice) -> None:
    fake_omnivoice.cls.error = OSError("no network")

    with pytest.raises(TtsError, match="Could not load the voice model"):
        OmniVoiceTts("missing/model").synthesize("Hello")


def test_generation_failure_becomes_a_tts_error(fake_omnivoice) -> None:
    provider = OmniVoiceTts(instruct="calm, sunny")
    provider.load()  # weights are fine; the prompt is what blows up
    fake_omnivoice.cls.error = ValueError("Unsupported instruct items")

    with pytest.raises(TtsError, match="Voice synthesis failed"):
        provider.synthesize("Hello")


def test_missing_package_reports_the_switch_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "omnivoice", None)

    with pytest.raises(TtsError, match="omnivoice is not installed"):
        OmniVoiceTts().synthesize("Hello")


def test_empty_model_output_is_an_error() -> None:
    provider = OmniVoiceTts()
    provider._model = SimpleNamespace(generate=lambda **_kwargs: [], sampling_rate=24_000)

    with pytest.raises(TtsError, match="Synthesis produced no audio"):
        provider.synthesize("Hello")


def test_speechify_still_strips_reply_markup() -> None:
    assert speechify("hello") == "hello"
    assert speechify("") == ""
