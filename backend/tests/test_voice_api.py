"""Voice HTTP surface: status, listen / recognize / speak, events, config.

Mirrors `backend/luxion/api/routes/voice.py`. Everything except the status
read is driven through an injected manager so no test opens a microphone or
plays audio; the config round trip uses the real store (a shared fixture wipes
`voice.json` around every test so the session data directory stays clean).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from luxion.api.routes import voice as voice_routes
from luxion.api.routes.voice import VoiceConfigPatch
from luxion.config.settings import VoiceConfig, get_settings, reset_settings_cache
from luxion.config.voice_override import clear_overrides, load_overrides
from luxion.voice.manager import VoiceError, VoiceEvent, VoiceStatus


class FakeVoiceManager:
    """The route-facing half of `VoiceManager` with hardware behind a flag."""

    def __init__(self) -> None:
        self.listening = False
        self.spoken: list[str] = []
        self.stopped = 0
        self.recognized_timeouts: list[float | None] = []
        self.fail_with: str | None = None

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            enabled=True,
            state="listening" if self.listening else "idle",
            listening=self.listening,
            armed=False,
            speaking=bool(self.spoken),
            stt={"provider": "whisper", "model": "base.en", "loaded": True},
            tts={"provider": "windows", "enabled": True, "rate": 0, "volume": 100},
            wake={"enabled": True, "phrase": "hey luxion", "armed_for_s": 0.0},
            capture={"device": "System default", "barge_in": True},
            microphone={"allowed": True, "state": "granted", "reason": "allowed"},
            speaker={"allowed": True, "state": "granted", "reason": "allowed"},
        )

    def _maybe_fail(self) -> None:
        if self.fail_with:
            raise VoiceError(self.fail_with)

    def start_listening(self) -> VoiceStatus:
        self._maybe_fail()
        self.listening = True
        return self.status()

    def stop_listening(self) -> VoiceStatus:
        self.listening = False
        return self.status()

    def recognize(self, timeout_s: float | None = None) -> str:
        self._maybe_fail()
        self.recognized_timeouts.append(timeout_s)
        return "hello from the microphone"

    def speak(self, text: str, *, block: bool = True) -> dict:
        self._maybe_fail()
        self.spoken.append(text)
        return {"started": True, "interrupted": False}

    def stop_speaking(self) -> bool:
        self.stopped += 1
        return True

    async def events(self) -> AsyncIterator[VoiceEvent]:
        yield VoiceEvent(type="command", text="open chrome", wake=True)
        yield VoiceEvent(type="spoken", interrupted=True)


@pytest.fixture
def fake_manager() -> FakeVoiceManager:
    return FakeVoiceManager()


@pytest.fixture
def voice_client(client: TestClient, fake_manager: FakeVoiceManager, monkeypatch):
    monkeypatch.setattr(voice_routes, "get_voice_manager", lambda: fake_manager)
    return client


@pytest.fixture(autouse=True)
def clean_overlay():
    """`voice.json` is shared process state — never leave a test's edits behind."""
    data_dir = get_settings().app.data_dir
    clear_overrides(data_dir)
    reset_settings_cache()
    yield
    clear_overrides(data_dir)
    reset_settings_cache()


# --------------------------------------------------------------------- status
def test_status_round_trip_through_the_real_manager(client: TestClient) -> None:
    body = client.get("/api/voice").json()

    assert set(body) == {
        "enabled",
        "state",
        "listening",
        "armed",
        "speaking",
        "stt",
        "tts",
        "wake",
        "capture",
        "device",
        "devices",
        "microphone",
        "speaker",
        "last_error",
    }
    assert body["state"] in {"idle", "listening", "transcribing", "speaking"}
    assert body["listening"] is False, "no test may leave the microphone open"
    assert {"allowed", "state", "reason"} <= set(body["microphone"])


def test_status_reflects_the_injected_session(voice_client: TestClient, fake_manager) -> None:
    assert voice_client.get("/api/voice").json()["listening"] is False

    voice_client.post("/api/voice/listen", json={"on": True})
    assert voice_client.get("/api/voice").json()["listening"] is True

    voice_client.post("/api/voice/listen", json={"on": False})
    assert voice_client.get("/api/voice").json()["listening"] is False


# --------------------------------------------------------- listen / recognize
def test_listen_toggle_uses_the_body_flag(voice_client: TestClient, fake_manager) -> None:
    started = voice_client.post("/api/voice/listen", json={"on": True})
    assert started.status_code == 200
    assert started.json()["listening"] is True

    stopped = voice_client.post("/api/voice/listen", json={"on": False})
    assert stopped.json()["listening"] is False
    assert fake_manager.listening is False


def test_recognize_returns_the_transcript(voice_client: TestClient, fake_manager) -> None:
    body = voice_client.post("/api/voice/recognize", json={}).json()
    assert body == {"text": "hello from the microphone"}
    assert fake_manager.recognized_timeouts == [None]

    voice_client.post("/api/voice/recognize", json={"timeout_s": 7.5})
    assert fake_manager.recognized_timeouts == [None, 7.5]


def test_recognize_timeout_is_bounded(voice_client: TestClient) -> None:
    assert voice_client.post("/api/voice/recognize", json={"timeout_s": 0.5}).status_code == 422
    assert voice_client.post("/api/voice/recognize", json={"timeout_s": 999}).status_code == 422


def test_voice_errors_become_400_with_the_reason(
    voice_client: TestClient, fake_manager: FakeVoiceManager
) -> None:
    fake_manager.fail_with = "microphone is turned off in Luxion"

    response = voice_client.post("/api/voice/listen", json={"on": True})

    assert response.status_code == 400
    assert response.json()["detail"] == "microphone is turned off in Luxion"
    assert fake_manager.listening is False


# -------------------------------------------------------------------- playback
def test_speak_and_stop(voice_client: TestClient, fake_manager: FakeVoiceManager) -> None:
    spoken = voice_client.post("/api/voice/speak", json={"text": "hello", "block": True})
    assert spoken.status_code == 200
    assert fake_manager.spoken == ["hello"]

    stopped = voice_client.post("/api/voice/stop")
    assert stopped.json() == {"stopped": True}
    assert fake_manager.stopped == 1


def test_speak_rejects_a_blank_body(voice_client: TestClient) -> None:
    assert voice_client.post("/api/voice/speak", json={}).status_code == 422
    assert voice_client.post("/api/voice/speak", json={"text": ""}).status_code == 422


# ---------------------------------------------------------------------- events
def test_events_stream_framed_as_sse(voice_client: TestClient) -> None:
    with voice_client.stream("GET", "/api/voice/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join(response.iter_lines())

    assert "event: command" in payload
    assert '"text":"open chrome"' in payload
    assert "event: spoken" in payload
    assert '"interrupted":true' in payload


# ---------------------------------------------------------------------- config
def test_config_read_returns_effective_values_and_defaults(client: TestClient) -> None:
    bundle = client.get("/api/voice/config").json()

    assert set(bundle) == {"config", "defaults"}
    assert bundle["defaults"] == VoiceConfig().model_dump()
    assert set(bundle["config"]) == set(VoiceConfig.model_fields)
    assert bundle["config"]["wake_phrase"] == "hey luxion"


def test_config_patch_covers_every_voice_knob() -> None:
    assert VoiceConfigPatch.model_config.get("extra") == "forbid"
    assert set(VoiceConfigPatch.model_fields) == set(VoiceConfig.model_fields)
    for name, field in VoiceConfigPatch.model_fields.items():
        assert "None" in str(field.annotation), f"{name} must accept None (partial patch)"


def test_config_patch_persists_and_merges(voice_client: TestClient) -> None:
    first = voice_client.put("/api/voice/config", json={"tts_rate": 30})
    assert first.status_code == 200
    assert first.json()["state"] == "idle", "the session is rebuilt after a config write"

    second = voice_client.put("/api/voice/config", json={"wake_phrase": "computer"})
    assert second.status_code == 200

    config = voice_client.get("/api/voice/config").json()["config"]
    assert config["tts_rate"] == 30, "an earlier knob must survive a later patch"
    assert config["wake_phrase"] == "computer"
    assert load_overrides(get_settings().app.data_dir) == {
        "tts_rate": 30,
        "wake_phrase": "computer",
    }


def test_config_reset_returns_to_defaults(voice_client: TestClient) -> None:
    voice_client.put("/api/voice/config", json={"tts_rate": 30})
    assert voice_client.delete("/api/voice/config").status_code == 200

    bundle = voice_client.get("/api/voice/config").json()
    assert bundle["config"] == bundle["defaults"]
    assert load_overrides(get_settings().app.data_dir) == {}


def test_config_validation(voice_client: TestClient) -> None:
    assert voice_client.put("/api/voice/config", json={}).status_code == 400
    assert voice_client.put("/api/voice/config", json={"nope": 1}).status_code == 422
    assert voice_client.put("/api/voice/config", json={"master": "maybe"}).status_code == 422

    # Range checks live on VoiceConfig, not on the patch: an out-of-range value
    # is dropped by the overlay instead of failing the request (never fatal).
    accepted = voice_client.put("/api/voice/config", json={"tts_rate": 4000})
    assert accepted.status_code == 200
    assert voice_client.get("/api/voice/config").json()["config"]["tts_rate"] == 0
    assert load_overrides(get_settings().app.data_dir) == {}
