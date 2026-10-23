"""Voice + face second factors (PRD §27, §28, §33.2, Phase 11c).

Hermetic by design: the microphone is replaced by ``set_recorder`` (or a WAV
file written on the fly), and the two OpenCV networks are replaced by tiny
fakes, so the suite never opens a device, never downloads a 37 MB ONNX blob
and never depends on the host's Windows camera/mic privacy setting.

The maths that *is* real — MFCC extraction, dynamic time warping, the profile
store and the three safety rails — runs for real, because that is exactly the
code that has to be correct for the feature to mean anything.
"""

from __future__ import annotations

import asyncio
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from luxion.config.settings import Settings
from luxion.security.capabilities import get_capabilities, reset_capabilities
from luxion.vision import auth
from luxion.vision.imaging import VisionError

TARGET_RATE = 16_000


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_seams():
    """No fake recorder or cached face model may leak between tests."""
    auth.reset_recorder()
    auth.reset_face_models()
    reset_capabilities()
    yield
    auth.reset_recorder()
    auth.reset_face_models()
    reset_capabilities()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app={"data_dir": str(tmp_path), "logs_dir": str(tmp_path)},
        security={"autonomy_level": 5, "allowed_workspaces": [tmp_path]},
        biometrics={"mode": "voice_face"},
    )


def _grant_biometrics(settings: Settings) -> None:
    """The capability ships OFF (PRD §39) — turn it on for the test."""
    get_capabilities(settings).set("biometrics", "granted")


# --------------------------------------------------------------- synthetic audio
def _tone(*frequencies: float, seconds: float = 1.5, rate: int = TARGET_RATE) -> np.ndarray:
    """A crude 'vowel' — a few harmonics over a little noise, loud enough for VAD."""
    count = int(seconds * rate)
    time = np.arange(count, dtype=np.float64) / rate
    signal = np.zeros(count, dtype=np.float64)
    for index, frequency in enumerate(frequencies, start=1):
        signal += np.sin(2 * np.pi * frequency * time) / index
    signal += 0.01 * np.random.default_rng(abs(hash(tuple(frequencies))) % (2**32)).normal(
        0, 1, count
    )
    return (0.5 * signal / np.max(np.abs(signal))).astype(np.float32)


#: Two clearly different "speakers".
_VOICE_A = _tone(120, 240, 480)
_VOICE_B = _tone(300, 610, 920)


def _write_wav(path: Path, samples: np.ndarray, rate: int = TARGET_RATE) -> Path:
    """A real 16-bit PCM WAV so ``load_wav`` exercises the stdlib ``wave`` path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm.tobytes())
    return path


# ------------------------------------------------------------------- MFCC + DTW
def test_voice_features_have_the_declared_shape() -> None:
    features = auth.voice_features(_VOICE_A)
    assert features.shape[1] == auth.FEATURE_DIM  # 13 static + 13 deltas
    assert features.shape[0] > 5  # ~1s of speech at a 10 ms hop


def test_voice_features_survive_an_empty_clip() -> None:
    assert auth.voice_features(np.zeros(0, dtype=np.float32)).shape == (0, auth.FEATURE_DIM)
    assert auth.mfcc(np.zeros(0, dtype=np.float32)).shape == (0, 13)


def test_dtw_of_identical_sequences_is_zero() -> None:
    features = auth.voice_features(_VOICE_A)
    assert auth.dtw_distance(features, features) == pytest.approx(0.0, abs=1e-9)


def test_dtw_rejects_mismatched_shapes_and_empty_input() -> None:
    features = auth.voice_features(_VOICE_A)
    with pytest.raises(VisionError):
        auth.dtw_distance(features, features[:, :5])
    with pytest.raises(VisionError) as excinfo:
        auth.dtw_distance(features, np.zeros((0, features.shape[1])))
    assert excinfo.value.code == "auth_no_speech"


def test_same_voice_scores_far_higher_than_a_different_one() -> None:
    same = auth.voice_similarity(_VOICE_A, _VOICE_A)
    other = auth.voice_similarity(_VOICE_A, _VOICE_B)
    assert same == pytest.approx(1.0)  # 1 / (1 + 0)
    assert same > other
    assert 0.0 < other < same


# --------------------------------------------------------------------- load_wav
def test_load_wav_reads_a_stereo_file_down_to_mono(tmp_path: Path) -> None:
    mono = _tone(200, 400, seconds=0.5)
    stereo = np.stack([mono, mono * 0.5], axis=1)  # interleaved L/R
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)

    target = tmp_path / "stereo.wav"
    with wave.open(str(target), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TARGET_RATE)
        wav_file.writeframes(pcm.tobytes())

    samples, label = auth.load_wav(target)
    assert samples.dtype == np.float32
    assert label == "stereo.wav"
    assert samples.ndim == 1  # downmixed to mono


def test_load_wav_resamples_a_44k_file(tmp_path: Path) -> None:
    source = _tone(220, 440, seconds=0.4, rate=44_100)
    target = _write_wav(tmp_path / "hi.wav", source, rate=44_100)
    samples, _ = auth.load_wav(target)
    # ~0.4s at 16 kHz once resampled.
    assert 0.35 * TARGET_RATE < samples.size < 0.45 * TARGET_RATE


def test_load_wav_reports_a_missing_or_junk_file(tmp_path: Path) -> None:
    with pytest.raises(VisionError) as missing:
        auth.load_wav(tmp_path / "nope.wav")
    assert missing.value.code == "auth_audio_not_found"

    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"this is not a wave file at all")
    with pytest.raises(VisionError) as unreadable:
        auth.load_wav(junk)
    assert unreadable.value.code == "auth_audio_unreadable"


# ------------------------------------------------------------------ record_clip
def test_record_clip_uses_the_injected_recorder() -> None:
    auth.set_recorder(lambda duration_s, rate=None, device=None: _VOICE_A)
    captured = auth.record_clip(1.5)
    assert captured.dtype == np.float32
    assert captured.shape == _VOICE_A.shape

    auth.reset_recorder()


# ----------------------------------------------------------------- profile store
def test_profile_store_round_trips_and_replaces(settings: Settings, tmp_path: Path) -> None:
    store = auth.ProfileStore(settings)
    features = auth.voice_features(_VOICE_A)

    key, entry = store.save("voice", "Harsh", [features], {"enrolled_at": "now"})
    assert key == "harsh" and entry["name"] == "Harsh" and entry["samples"] == 1
    assert store.count("voice") == 1
    assert store.find("voice", "harsh") is not None
    assert store.find("voice", "HARSH") is not None  # case-insensitive

    loaded = store.load("voice", key)
    assert len(loaded) == 1 and loaded[0].shape == features.shape

    # Enrolling the same name again replaces, it does not add a second profile.
    store.save("voice", "Harsh", [features * 2], {"enrolled_at": "later"})
    assert store.count("voice") == 1
    assert store.load("voice", key)[0].shape == features.shape

    assert store.delete("voice", "harsh") is True
    assert store.count("voice") == 0
    assert store.delete("voice", "harsh") is False  # already gone


def test_profile_store_enforces_the_five_profile_cap(settings: Settings) -> None:
    store = auth.ProfileStore(settings)
    features = auth.voice_features(_VOICE_A)
    for index in range(settings.biometrics.max_profiles):
        store.save("voice", f"speaker-{index}", [features], {})

    assert store.count("voice") == 5
    with pytest.raises(VisionError) as excinfo:
        store.save("voice", "speaker-six", [features], {})
    assert excinfo.value.code == "auth_profile_limit"

    # A bad name is refused outright, not silently slugified into nothing.
    with pytest.raises(VisionError) as bad:
        store.save("voice", "!!!", [features], {})
    assert bad.value.code == "auth_bad_name"


def test_profile_store_survives_a_corrupt_index(settings: Settings) -> None:
    store = auth.ProfileStore(settings)
    store.directory.mkdir(parents=True, exist_ok=True)
    store.index_path.write_text("{not json", encoding="utf-8")
    assert store.list("voice") == []  # falls back to empty, never raises


# ----------------------------------------------------------------------- rails
def test_require_factor_respects_the_security_mode(settings: Settings) -> None:
    _grant_biometrics(settings)
    settings.biometrics.mode = "disabled"
    with pytest.raises(VisionError) as off:
        auth.require_factor(settings, "voice")
    assert off.value.code == "auth_mode_disabled"

    settings.biometrics.mode = "voice_only"
    auth.require_factor(settings, "voice")  # allowed
    with pytest.raises(VisionError) as face_off:
        auth.require_factor(settings, "face")
    assert face_off.value.code == "auth_mode_disabled"


def test_require_factor_is_blocked_by_the_off_capability(settings: Settings) -> None:
    settings.biometrics.mode = "voice_face"
    # Capability ships OFF — the default OFF consent blocks even with the mode on.
    with pytest.raises(VisionError) as excinfo:
        auth.require_factor(settings, "voice")
    assert excinfo.value.code == "auth_capability_denied"

    _grant_biometrics(settings)
    auth.require_factor(settings, "voice")  # no raise


def test_require_factor_rejects_an_unknown_modality(settings: Settings) -> None:
    with pytest.raises(VisionError) as excinfo:
        auth.require_factor(settings, "retina")
    assert excinfo.value.code == "auth_bad_modality"


def test_require_hardware_follows_the_os_consent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "deny")
    with pytest.raises(VisionError) as blocked:
        auth.require_hardware(settings, "microphone")
    assert blocked.value.code == "auth_microphone_denied"


# ------------------------------------------------------------ voice (end to end)
def test_enroll_then_verify_the_same_voice_matches(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grant_biometrics(settings)
    clip = _write_wav(tmp_path / "me.wav", _VOICE_A)

    enrolled = run(auth.enroll_voice(settings, "harsh", path=clip))
    assert enrolled["modality"] == "voice" and enrolled["name"] == "harsh"
    assert enrolled["profiles"] == 1 and enrolled["frames"] > 5

    outcome = run(auth.verify_voice(settings, "harsh", path=clip))
    assert outcome["matched"] is True
    assert outcome["profile"] == "harsh"
    assert outcome["score"] >= settings.biometrics.voice_threshold


def test_verify_a_different_voice_does_not_match(settings: Settings, tmp_path: Path) -> None:
    _grant_biometrics(settings)
    clip_a = _write_wav(tmp_path / "a.wav", _VOICE_A)
    clip_b = _write_wav(tmp_path / "b.wav", _VOICE_B)

    run(auth.enroll_voice(settings, "harsh", path=clip_a))
    outcome = run(auth.verify_voice(settings, "harsh", path=clip_b))
    assert outcome["matched"] is False
    assert outcome["profile"] is None


def test_verify_without_a_name_scores_every_profile(settings: Settings, tmp_path: Path) -> None:
    _grant_biometrics(settings)
    clip_a = _write_wav(tmp_path / "a.wav", _VOICE_A)
    clip_b = _write_wav(tmp_path / "b.wav", _VOICE_B)

    run(auth.enroll_voice(settings, "alpha", path=clip_a))
    run(auth.enroll_voice(settings, "bravo", path=clip_b))

    outcome = run(auth.verify_voice(settings, path=clip_b))
    assert outcome["matched"] is True
    assert outcome["profile"] == "bravo"  # the best-scoring profile wins
    assert {c["name"] for c in outcome["candidates"]} == {"alpha", "bravo"}


def test_verify_voice_without_any_profile_is_a_clear_error(
    settings: Settings, tmp_path: Path
) -> None:
    _grant_biometrics(settings)
    clip = _write_wav(tmp_path / "me.wav", _VOICE_A)
    with pytest.raises(VisionError) as excinfo:
        run(auth.verify_voice(settings, path=clip))
    assert excinfo.value.code == "auth_no_profile"


def test_enroll_voice_uses_the_microphone_when_no_file_is_given(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grant_biometrics(settings)
    monkeypatch.setattr("luxion.security.capabilities.probe_os_consent", lambda key: "allow")
    auth.set_recorder(lambda duration_s, rate=None, device=None: _VOICE_A)

    enrolled = run(auth.enroll_voice(settings, "harsh"))
    assert enrolled["source"]  # a device name, not a filename
    assert enrolled["duration_s"] > 0


def test_enroll_voice_refuses_a_silent_clip(settings: Settings, tmp_path: Path) -> None:
    _grant_biometrics(settings)
    silent = _write_wav(tmp_path / "quiet.wav", np.zeros(TARGET_RATE, dtype=np.float32))
    with pytest.raises(VisionError) as excinfo:
        run(auth.enroll_voice(settings, "harsh", path=silent))
    assert excinfo.value.code == "auth_no_speech"


# -------------------------------------------------------------- face (end to end)
class _FakeDetector:
    """Enough of ``cv2.FaceDetectorYN`` for ``face_embedding``."""

    def __init__(self, faces: np.ndarray) -> None:
        self._faces = faces
        self.sizes: list[tuple[int, int]] = []

    def setInputSize(self, size) -> None:  # noqa: N802 - mirrors the OpenCV API
        self.sizes.append(tuple(size))

    def detect(self, frame):  # noqa: ANN201, ANN001
        return None, self._faces


class _FakeRecognizer:
    """Enough of ``cv2.FaceRecognizerSF`` for ``face_embedding``.

    ``match`` is an instance method (a ``method_descriptor`` in the OpenCV 5
    bindings), so the fake mirrors that — the production code calls it on the
    recognizer instance, and a ``@staticmethod`` here would hide a regression.
    """

    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = np.asarray(embedding, dtype=np.float32).reshape(1, -1)

    def alignCrop(self, frame, face):  # noqa: N802, ANN201, ANN001
        return frame

    def feature(self, aligned):  # noqa: ANN201, ANN001
        return self._embedding

    def match(self, first, second, dis_type):  # noqa: ANN001, ANN201
        """A real cosine similarity, so enroll→verify of one embedding scores 1.0.

        ``dis_type`` is the integer the OpenCV 5 bindings require (``0`` =
        FR_COSINE), not a string — mirroring that keeps the tests honest about
        the call shape.
        """
        assert dis_type == 0, "face_similarity must ask for cosine (dis_type 0)"
        left = np.asarray(first, dtype=np.float32).reshape(-1)
        right = np.asarray(second, dtype=np.float32).reshape(-1)
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        return float(np.dot(left, right) / denominator) if denominator else 0.0


def _embedding(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 1, 128).astype(np.float32)


def _install_face(monkeypatch: pytest.MonkeyPatch, faces: np.ndarray, embedding: np.ndarray):
    monkeypatch.setattr(auth, "_detector", lambda settings: _FakeDetector(faces))
    monkeypatch.setattr(auth, "_recognizer", lambda settings: _FakeRecognizer(embedding))


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 48), (10, 20, 30)).save(path, format="PNG")
    return path


def test_face_embedding_picks_the_most_confident_face(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    faces = np.array([[5, 5, 20, 20, 0.70], [10, 10, 30, 30, 0.95]], dtype=np.float32)
    _install_face(monkeypatch, faces, _embedding(1))

    face = auth.face_embedding(settings, _png(settings.app.data_dir / "probe.png"))
    assert face["embedding"].shape == (1, 128)
    assert face["score"] == pytest.approx(0.95, abs=1e-3)


def test_face_embedding_reports_a_frame_with_no_face(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_face(monkeypatch, np.zeros((0, 5), dtype=np.float32), _embedding(1))
    with pytest.raises(VisionError) as excinfo:
        auth.face_embedding(settings, _png(settings.app.data_dir / "empty.png"))
    assert excinfo.value.code == "auth_no_face"


def test_enroll_then_verify_the_same_face_matches(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grant_biometrics(settings)
    face = _embedding(7)
    _install_face(monkeypatch, np.array([[5, 5, 30, 30, 0.91]], dtype=np.float32), face)
    photo = _png(tmp_path / "me.png")

    enrolled = run(auth.enroll_face(settings, "harsh", path=photo))
    assert enrolled["modality"] == "face" and enrolled["name"] == "harsh"
    assert enrolled["profiles"] == 1 and enrolled["detection_score"] == pytest.approx(0.91)

    outcome = run(auth.verify_face(settings, "harsh", path=photo))
    assert outcome["matched"] is True
    assert outcome["profile"] == "harsh"
    assert outcome["score"] == pytest.approx(1.0)  # the very same embedding


def test_verify_a_different_face_does_not_match(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grant_biometrics(settings)
    photo = _png(tmp_path / "me.png")
    faces = np.array([[5, 5, 30, 30, 0.91]], dtype=np.float32)

    _install_face(monkeypatch, faces, _embedding(7))
    run(auth.enroll_face(settings, "harsh", path=photo))

    # A different, orthogonal embedding → cosine ≈ 0, far below the threshold.
    orthogonal = np.zeros(128, dtype=np.float32)
    orthogonal[0] = 1.0
    _install_face(monkeypatch, faces, orthogonal)
    outcome = run(auth.verify_face(settings, "harsh", path=photo))
    assert outcome["matched"] is False and outcome["profile"] is None


# --------------------------------------------------------------------- status
def test_auth_status_reports_policy_without_touching_a_device(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**_kwargs):
        raise AssertionError("auth_status opened a device")

    monkeypatch.setattr(auth, "capture_frame", _boom)

    status = auth.auth_status(settings)
    assert status["mode"] == "voice_face"
    assert status["max_profiles"] == 5
    assert set(status["profiles"]) == {"voice", "face"}
    assert status["profiles"] == {"voice": 0, "face": 0}
    assert status["models_ready"] is False  # nothing downloaded yet
    assert set(status["models"]) == {"yunet", "sface"}
    assert status["biometrics"]["state"] == "denied"  # the capability ships OFF


def test_models_ready_reflects_presence_only(settings: Settings) -> None:
    assert auth.models_ready(settings) == {"yunet": False, "sface": False}

    directory = auth.model_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    for spec in auth.MODEL_SPECS.values():
        (directory / spec.filename).write_bytes(b"0" * (spec.min_bytes + 1))

    assert auth.models_ready(settings) == {"yunet": True, "sface": True}


def test_delete_profile_and_list_profiles(settings: Settings, tmp_path: Path) -> None:
    _grant_biometrics(settings)
    clip = _write_wav(tmp_path / "me.wav", _VOICE_A)
    run(auth.enroll_voice(settings, "harsh", path=clip))

    grouped = auth.list_profiles(settings)
    assert [p["name"] for p in grouped["voice"]] == ["harsh"]
    assert grouped["face"] == []

    assert auth.delete_profile(settings, "voice", "harsh") is True
    assert auth.list_profiles(settings)["voice"] == []
    with pytest.raises(VisionError):
        auth.delete_profile(settings, "retina", "harsh")


def test_json_index_is_valid_on_disk(settings: Settings, tmp_path: Path) -> None:
    _grant_biometrics(settings)
    clip = _write_wav(tmp_path / "me.wav", _VOICE_A)
    run(auth.enroll_voice(settings, "harsh", path=clip))

    index = json.loads((settings.app.data_dir / "biometrics" / "profiles.json").read_text())
    assert "harsh" in index["voice"]
    assert index["voice"]["harsh"]["name"] == "harsh"
