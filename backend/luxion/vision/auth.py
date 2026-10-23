"""Voice + face second factors (PRD §27, §28, §33.2, Phase 11c).

Two local biometric paths behind one contract — *who is speaking* and *who is
on camera* — and neither leaves the box:

========  ===============================================================  =======
Modality  How it is matched                                                Cost
========  ===============================================================  =======
``voice`` MFCC (13 coefficients + 13 deltas) over numpy FFT/DCT, aligned   free,
          by dynamic time warping; ``similarity = 1 / (1 + mean DTW cost)`` local
``face``  OpenCV **YuNet** detection → **SFace** 128-D embedding →          one 37 MB
          cosine similarity (``FaceRecognizerSF.match``)                    download
========  ===============================================================  =======

**Zero extra dependencies beyond the OpenCV wheel Phase 11b already
added.** ``resemblyzer`` was rejected because it pins ``librosa<0.11`` (it
would downgrade the librosa 1.0.0 OmniVoice needs), and ``scipy`` is
deliberately *not* used: the mel filterbank and the DCT are matrix algebra, so
numpy — already a hard dependency — is enough and a fresh install carries no
undeclared requirement.

PRD §27 is explicit that this is **not** speech recognition: speech
recognition (:mod:`luxion.voice`) answers *what was said*, this module answers
*who said it*.

Safety rails, in the order they run:

1. the **``biometrics`` capability** (app consent, **default OFF**) — the four
   tools declare ``requires="biometrics"``, so the executor blocks before the
   risk engine runs (PRD §39);
2. the **security mode** (``disabled`` / ``voice_only`` / ``face_only`` /
   ``voice_face``, PRD §28) — which factors are even in play;
3. the **hardware gate** for the capture itself (``microphone`` / ``camera``),
   checked here because a tool may declare only one capability.

Templates live in ``<data_dir>/biometrics/`` (an ``profiles.json`` index plus
one ``.npz`` per profile) and the two ONNX models in
``<data_dir>/vision_models/`` — both are regenerated state, never secrets.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import numpy as np

from luxion.config.settings import Settings
from luxion.security.capabilities import get_capabilities
from luxion.vision.camera import capture_frame, frame_to_image, opencv_available
from luxion.vision.imaging import VisionError, decode_image
from luxion.voice.audio import (
    TARGET_RATE,
    AudioError,
    resample,
    resolve_input_device,
    rms,
)

logger = logging.getLogger(__name__)

Modality = Literal["voice", "face"]

#: The two modalities PRD §27/§28 describe, in the order the UI lists them.
MODALITIES: tuple[str, ...] = ("voice", "face")

#: PRD §28's four-state security configuration → the modalities it enables.
MODE_MODALITIES: dict[str, tuple[str, ...]] = {
    "disabled": (),
    "voice_only": ("voice",),
    "face_only": ("face",),
    "voice_face": ("voice", "face"),
}

MODALITY_LABELS = {"voice": "Voice", "face": "Face"}

# --------------------------------------------------------------- voice features
#: Analysis window / hop (the classic 25 ms / 10 ms speech pair).
_FRAME_S = 0.025
_HOP_S = 0.010
#: Zero-padded FFT size — 512 bins cover the 16 kHz band with room to spare.
_N_FFT = 512
_N_MELS = 26
#: Cepstra kept (index 0, the overall log energy, is dropped: it tracks how
#: loud the room was, not who was speaking).
_N_COEFFS = 13
_EPS = 1e-10
#: Feature vector width: 13 static coefficients + 13 first derivatives.
FEATURE_DIM = _N_COEFFS * 2


# ------------------------------------------------------------------- audio I/O
_RECORDER: Callable[..., np.ndarray] | None = None


def set_recorder(recorder: Callable[..., np.ndarray] | None) -> None:
    """Install a fake microphone capture (tests never open a real device)."""
    global _RECORDER  # noqa: PLW0603 - module seam, same shape as the other managers
    _RECORDER = recorder


def reset_recorder() -> None:
    """Drop the fake capture so the real microphone is used again."""
    set_recorder(None)


def load_wav(path: str | Path) -> tuple[np.ndarray, str]:
    """Read a WAV file into mono float32 samples at :data:`TARGET_RATE`.

    Supports the PCM widths real recordings use (8/16/32-bit integer);
    anything else raises a clear error instead of producing garbage features.
    """
    import wave  # noqa: PLC0415 - stdlib, only needed on this path

    target = Path(path)
    if not target.exists():
        raise VisionError(f"Audio file not found: {target}", code="auth_audio_not_found")
    try:
        with wave.open(str(target), "rb") as wav_file:
            width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except (wave.Error, OSError) as exc:
        raise VisionError(
            f"Could not read '{target.name}' as a WAV file: {exc}",
            code="auth_audio_unreadable",
        ) from exc

    if width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise VisionError(
            f"Unsupported WAV sample width {width * 8}-bit in '{target.name}'.",
            code="auth_audio_unsupported",
        )
    if samples.size == 0:
        raise VisionError(f"'{target.name}' contains no audio.", code="auth_no_speech")

    if channels > 1:
        usable = samples.size - (samples.size % channels)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    if rate and rate != TARGET_RATE:
        samples = resample(samples, int(rate), TARGET_RATE)
    return np.ascontiguousarray(samples, dtype=np.float32), target.name


def record_clip(
    duration_s: float,
    *,
    device: int | None = None,
    rate: int = TARGET_RATE,
) -> np.ndarray:
    """Capture one mono float32 clip from the microphone at ``rate``.

    Falls back to the device's own default rate when it refuses the speech
    rate (some USB headsets only open at 44.1/48 kHz) and resamples, because
    a failed capture must not look like "no speech".
    """
    if _RECORDER is not None:
        captured = _RECORDER(duration_s, rate=rate, device=device)
        return np.ascontiguousarray(np.asarray(captured, dtype=np.float32).reshape(-1))

    import sounddevice as sd  # noqa: PLC0415 - hardware import, kept off module load

    frames = max(1, int(round(duration_s * rate)))
    try:
        audio = sd.rec(frames, samplerate=rate, channels=1, dtype="float32", device=device)
        sd.wait()
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    except Exception:  # noqa: BLE001 - PortAudio raises bare Exception subclasses
        try:
            default_rate = int(sd.query_devices(device, "input")["default_samplerate"])
            audio = sd.rec(
                frames, samplerate=default_rate, channels=1, dtype="float32", device=device
            )
            sd.wait()
            samples = resample(np.asarray(audio, dtype=np.float32).reshape(-1), default_rate, rate)
        except Exception as exc:  # noqa: BLE001 - report the real failure, not the fallback's
            raise VisionError(
                f"Could not record from the microphone: {exc}",
                code="auth_mic_unavailable",
            ) from exc
    if samples.size == 0:
        raise VisionError("The microphone returned no audio.", code="auth_no_speech")
    return np.ascontiguousarray(samples, dtype=np.float32)


# ------------------------------------------------------------ MFCC + DTW (voice)
def _mel_filterbank(*, rate: int = TARGET_RATE) -> np.ndarray:
    """Triangular mel filters mapping FFT bins → mel bands (``n_fft/2+1 × mels``)."""

    def hz_to_mel(freq: Any) -> Any:
        return 2595.0 * np.log10(1.0 + np.asarray(freq) / 700.0)

    def mel_to_hz(mel: Any) -> Any:
        return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)

    points = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(rate / 2.0), _N_MELS + 2))
    bins = np.floor((_N_FFT + 1) * points / rate).astype(int)
    bins = np.clip(bins, 0, _N_FFT // 2)

    bank = np.zeros((_N_FFT // 2 + 1, _N_MELS), dtype=np.float64)
    for index in range(_N_MELS):
        left, centre, right = bins[index], bins[index + 1], bins[index + 2]
        if centre <= left:
            centre = min(left + 1, _N_FFT // 2)
        if right <= centre:
            right = centre + 1
        rising = np.arange(left, centre)
        falling = np.arange(centre, right)
        bank[rising, index] = (rising - left) / max(centre - left, 1)
        bank[falling, index] = (right - falling) / max(right - centre, 1)
    return bank


#: Built once — it only depends on constants.
_MEL_BANK = _mel_filterbank()

#: DCT-II basis for coefficients 1..13 of a 26-band log-mel spectrum.
_DCT = np.cos(
    np.pi * np.arange(1, _N_COEFFS + 1)[:, None] * (np.arange(_N_MELS)[None, :] + 0.5) / _N_MELS
)


def mfcc(samples: np.ndarray, *, rate: int = TARGET_RATE) -> np.ndarray:
    """Mel-cepstral coefficients of a clip → ``(frames, 13)``.

    Pre-emphasis → 25 ms Hamming frames → rFFT power spectrum → mel filterbank
    → log → DCT-II. The mean is subtracted over time (cepstral mean
    normalisation) so the microphone's colouring and the recording level drop
    out and only the speaker's vocal-tract shape remains.
    """
    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    if audio.size == 0:
        return np.zeros((0, _N_COEFFS), dtype=np.float64)

    # Pre-emphasis flattens the spectral tilt of the glottal source.
    audio = np.concatenate(([audio[0]], audio[1:] - 0.97 * audio[:-1]))

    frame_len = max(2, int(_FRAME_S * rate))
    hop = max(1, int(_HOP_S * rate))
    if audio.size < frame_len:
        audio = np.pad(audio, (0, frame_len - audio.size))
    n_frames = 1 + (audio.size - frame_len) // hop
    starts = np.arange(n_frames)[:, None] * hop
    frames = audio[starts + np.arange(frame_len)[None, :]] * np.hamming(frame_len)

    spectrum = np.fft.rfft(frames, n=_N_FFT, axis=1)
    power = spectrum.real**2 + spectrum.imag**2
    mel = np.maximum(power @ _MEL_BANK, _EPS)
    coefficients = np.log(mel) @ _DCT.T

    coefficients -= coefficients.mean(axis=0, keepdims=True)
    return coefficients


def voice_features(samples: np.ndarray, *, rate: int = TARGET_RATE) -> np.ndarray:
    """Static + delta coefficients → ``(frames, 26)``.

    The deltas carry how the spectrum moves, which is most of what separates
    one voice from another once the static shape is normalised away.
    """
    static = mfcc(samples, rate=rate)
    if static.shape[0] == 0:
        return np.zeros((0, FEATURE_DIM), dtype=np.float64)
    if static.shape[0] == 1:
        deltas = np.zeros_like(static)
    else:
        deltas = np.zeros_like(static)
        deltas[1:-1] = (static[2:] - static[:-2]) / 2.0
        deltas[0] = static[1] - static[0]
        deltas[-1] = static[-1] - static[-2]
    return np.concatenate([static, deltas], axis=1)


def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean local cost along the optimal alignment path (dynamic time warping).

    Normalising by the path length — not by ``n×m`` — is what lets a slightly
    longer "hello, my name is…" line match a shorter one without the score
    collapsing towards zero. Returns a value ≥ 0 where ``0`` means the two
    sequences are identical.
    """
    left = np.asarray(a, dtype=np.float64)
    right = np.asarray(b, dtype=np.float64)
    if left.ndim != 2 or right.ndim != 2 or left.shape[1] != right.shape[1]:
        raise VisionError("Cannot compare voice samples of different feature shapes.")
    if left.shape[0] == 0 or right.shape[0] == 0:
        raise VisionError(
            "Not enough speech to compare — speak for a couple of seconds.",
            code="auth_no_speech",
        )

    cost = np.sqrt(((left[:, None, :] - right[None, :, :]) ** 2).sum(axis=-1)).tolist()
    rows, cols = len(cost), len(cost[0])

    table = [[float("inf")] * (cols + 1) for _ in range(rows + 1)]
    table[0][0] = 0.0
    for i in range(1, rows + 1):
        current, previous, row_cost = table[i], table[i - 1], cost[i - 1]
        for j in range(1, cols + 1):
            current[j] = row_cost[j - 1] + min(previous[j], current[j - 1], previous[j - 1])

    # Walk the path back to count it: cost/frames, not cost/cells.
    i, j = rows, cols
    steps = 0
    while i or j:
        steps += 1
        if i == 0:
            j -= 1
        elif j == 0:
            i -= 1
        else:
            diagonal = table[i - 1][j - 1]
            best = min(table[i - 1][j], table[i][j - 1], diagonal)
            if best == diagonal:
                i, j = i - 1, j - 1
            elif best == table[i - 1][j]:
                i -= 1
            else:
                j -= 1
    return float(table[rows][cols] / max(steps, 1))


def voice_similarity(first: np.ndarray, second: np.ndarray, *, rate: int = TARGET_RATE) -> float:
    """Similarity of two raw clips, ``0..1`` (``1`` = the same voice)."""
    distance = dtw_distance(voice_features(first, rate=rate), voice_features(second, rate=rate))
    return 1.0 / (1.0 + distance)


# ------------------------------------------------------------------ face models
class _ModelSpec:
    __slots__ = ("filename", "url", "min_bytes")

    def __init__(self, filename: str, url: str, min_bytes: int) -> None:
        self.filename = filename
        self.url = url
        self.min_bytes = min_bytes


#: OpenCV 5.0 ships **no** model files (``cv2/data/`` holds only an
#: ``__init__.py``), so both networks come from the Apache-2.0 ``opencv_zoo``
#: repository on first use — the same "download once, then cache" contract as
#: the whisper and embedding models.
MODEL_SPECS: dict[str, _ModelSpec] = {
    "yunet": _ModelSpec(
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        100_000,
    ),
    "sface": _ModelSpec(
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx",
        10_000_000,
    ),
}

_DETECTOR_CACHE: dict[str, Any] = {}
_RECOGNIZER_CACHE: dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()


def face_api_available() -> bool:
    """True when this OpenCV build exposes both face networks (import check)."""
    if not opencv_available():
        return False
    import cv2  # noqa: PLC0415

    return hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")


def model_dir(settings: Settings) -> Path:
    return Path(settings.app.data_dir) / "vision_models"


def model_path(settings: Settings, name: str) -> Path:
    spec = MODEL_SPECS.get(name)
    if spec is None:
        raise VisionError(f"Unknown face model '{name}'.", code="auth_model_unknown")
    return model_dir(settings) / spec.filename


def models_ready(settings: Settings) -> dict[str, bool]:
    """Presence check only — never downloads, never opens a device."""
    ready: dict[str, bool] = {}
    for name, spec in MODEL_SPECS.items():
        path = model_dir(settings) / spec.filename
        try:
            ready[name] = path.exists() and path.stat().st_size >= spec.min_bytes
        except OSError:
            ready[name] = False
    return ready


def ensure_model(settings: Settings, name: str) -> Path:
    """Return the model file, downloading it into ``<data_dir>/vision_models``.

    Write-then-rename, like every other file this project persists, so a
    half-downloaded 37 MB blob can never be mistaken for the real thing.
    """
    path = model_path(settings, name)
    spec = MODEL_SPECS[name]
    try:
        if path.exists() and path.stat().st_size >= spec.min_bytes:
            return path
    except OSError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    logger.info("biometric_model_download name=%s", name)
    try:
        import httpx  # noqa: PLC0415 - only needed on the first use of the feature

        with httpx.stream("GET", spec.url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            written = 0
            with open(temp, "wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
                    written += len(chunk)
        if written < spec.min_bytes:
            raise VisionError(
                f"The {name} face model arrived truncated ({written} bytes). "
                "Check the connection and try again.",
                code="auth_model_download_failed",
            )
        os.replace(temp, path)
    except VisionError:
        temp.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - httpx + OS errors on the download path
        temp.unlink(missing_ok=True)
        raise VisionError(
            f"Could not download the {name} face model ({spec.filename}): {exc}. "
            "Face authentication needs it once; afterwards it works offline.",
            code="auth_model_download_failed",
        ) from exc
    logger.info("biometric_model_ready name=%s bytes=%s", name, path.stat().st_size)
    return path


def reset_face_models() -> None:
    """Drop the cached detector/recognizer (tests and model swaps)."""
    with _MODEL_LOCK:
        _DETECTOR_CACHE.clear()
        _RECOGNIZER_CACHE.clear()


def _cv2() -> Any:
    try:
        import cv2  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - installed with the backend
        raise VisionError(
            "OpenCV is required for face authentication (pip install opencv-contrib-python).",
            code="face_dependency_missing",
        ) from exc
    return cv2


def _detector(settings: Settings) -> Any:
    path = ensure_model(settings, "yunet")
    key = str(path)
    with _MODEL_LOCK:
        cached = _DETECTOR_CACHE.get(key)
        if cached is None:
            cv2 = _cv2()
            if not hasattr(cv2, "FaceDetectorYN"):
                raise VisionError(
                    "This OpenCV build has no face detector (install "
                    "opencv-contrib-python, not just opencv-python).",
                    code="face_dependency_missing",
                )
            cached = cv2.FaceDetectorYN.create(
                key, "", (320, 320), score_threshold=0.6, nms_threshold=0.3, top_k=5000
            )
            _DETECTOR_CACHE[key] = cached
    return cached


def _recognizer(settings: Settings) -> Any:
    path = ensure_model(settings, "sface")
    key = str(path)
    with _MODEL_LOCK:
        cached = _RECOGNIZER_CACHE.get(key)
        if cached is None:
            cv2 = _cv2()
            if not hasattr(cv2, "FaceRecognizerSF"):
                raise VisionError(
                    "This OpenCV build has no face recognizer (install opencv-contrib-python).",
                    code="face_dependency_missing",
                )
            cached = cv2.FaceRecognizerSF.create(key, "")
            _RECOGNIZER_CACHE[key] = cached
    return cached


def _to_bgr(image: Any) -> Any:
    """PIL image → contiguous BGR ``uint8``, the layout OpenCV expects."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def face_embedding(settings: Settings, source: Any, *, label: str | None = None) -> dict[str, Any]:
    """Detect the most confident face in ``source`` and embed it.

    Returns ``{"embedding": (1, 128) float32, "score": detection confidence,
    "source": label, "recognizer": <cached recognizer>}``. Exactly one face is
    embedded because "which of these three people enrolled?" is not a question
    this feature can answer honestly. The recognizer rides along so a caller
    scoring several candidates reuses the cached instance (``match`` is an
    instance method in OpenCV 5).
    """
    image, name = decode_image(source, label=label)
    frame = _to_bgr(image)

    detector = _detector(settings)
    detector.setInputSize((frame.shape[1], frame.shape[0]))
    _found, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        raise VisionError(
            "No face was detected in the image. Face the camera in good light "
            "and keep one face in the frame.",
            code="auth_no_face",
        )
    faces = np.asarray(faces)
    best = faces[int(np.argmax(faces[:, -1]))]

    recognizer = _recognizer(settings)
    aligned = recognizer.alignCrop(frame, best)
    feature = np.asarray(recognizer.feature(aligned), dtype=np.float32).reshape(1, -1)
    if feature.shape[1] != 128:  # pragma: no cover - guards a model swap
        raise VisionError(
            f"Unexpected face embedding width {feature.shape[1]} (expected 128).",
            code="face_embedding_failed",
        )
    return {
        "embedding": feature,
        "score": round(float(best[-1]), 3),
        "source": name,
        "recognizer": recognizer,
    }


def face_similarity(first: Any, second: Any, recognizer: Any) -> float:
    """Cosine similarity of two SFace embeddings, ``-1..1`` (higher = same face).

    ``match`` is an *instance* method in the OpenCV 5 bindings (a
    ``method_descriptor``), so it must be called on a recognizer — the caller
    passes one in (usually the cached one :func:`face_embedding` returned) to
    avoid building a second recogniser per candidate.

    The distance type is the integer ``0`` (FR_COSINE), not the ``"cosine"``
    string older bindings accepted: OpenCV 5.0.0's ``match`` raises
    "dis_type is required to be an integer" for the string. ``0`` returns
    ``1.0`` for identical embeddings and ``0.0`` for orthogonal ones, so it is
    the cosine in ``[-1, 1]`` this threshold compares against.
    """
    left = np.asarray(first, dtype=np.float32).reshape(1, -1)
    right = np.asarray(second, dtype=np.float32).reshape(1, -1)
    score = recognizer.match(left, right, 0)  # 0 = FR_COSINE
    return float(np.asarray(score, dtype=np.float64).reshape(-1)[0])


# ----------------------------------------------------------------- profile store
def _slug(name: str) -> str:
    """Filesystem-safe profile key (the display name is kept in the index)."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", str(name).strip().lower()).strip("_")
    return cleaned[:32]


class ProfileStore:
    """The enrolled templates: ``<data_dir>/biometrics/`` index + ``.npz`` blobs.

    The index holds who is enrolled (and when); the arrays are the actual
    biometric material. Losing the ``.npz`` costs an enrollment, never the
    index — and the index is rebuilt from whatever files are left.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return Path(self.settings.app.data_dir) / "biometrics"

    @property
    def index_path(self) -> Path:
        return self.directory / "profiles.json"

    # index ------------------------------------------------------------
    def _read_index(self) -> dict[str, dict[str, dict[str, Any]]]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("biometrics_index_unreadable error=%s", exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        index: dict[str, dict[str, dict[str, Any]]] = {}
        for modality in MODALITIES:
            entries = raw.get(modality)
            if isinstance(entries, dict):
                index[modality] = {
                    str(key): dict(value)
                    for key, value in entries.items()
                    if isinstance(value, dict)
                }
            else:
                index[modality] = {}
        return index

    def _write_index(self, index: dict[str, dict[str, dict[str, Any]]]) -> None:
        if not any(index.values()):
            try:
                self.index_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("biometrics_index_not_removed error=%s", exc)
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        temp = self.index_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.index_path)

    # profiles ----------------------------------------------------------
    def list(self, modality: str) -> list[dict[str, Any]]:
        entries = self._read_index().get(modality, {})
        return sorted(entries.values(), key=lambda item: str(item.get("name", "")))

    def count(self, modality: str) -> int:
        return len(self._read_index().get(modality, {}))

    def find(self, modality: str, name: str) -> tuple[str, dict[str, Any]] | None:
        """Look a profile up by slug or by display name (case-insensitive)."""
        key = _slug(name)
        entries = self._read_index().get(modality, {})
        if key in entries:
            return key, entries[key]
        needle = str(name).strip().casefold()
        for slug, entry in entries.items():
            if str(entry.get("name", "")).casefold() == needle:
                return slug, entry
        return None

    def items(self, modality: str) -> list[tuple[str, dict[str, Any]]]:
        """Every ``(slug, entry)`` pair of one modality."""
        return list(self._read_index().get(modality, {}).items())

    def save(
        self,
        modality: str,
        name: str,
        arrays: list[np.ndarray],
        meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Store (or replace) one profile's templates + metadata."""
        with self._lock:
            index = self._read_index()
            profiles = index.setdefault(modality, {})
            limit = self.settings.biometrics.max_profiles
            key = _slug(name)
            if not key:
                raise VisionError(
                    "Give the profile a name with letters or numbers.",
                    code="auth_bad_name",
                )
            if key not in profiles and len(profiles) >= limit:
                raise VisionError(
                    f"{MODALITY_LABELS[modality]} already has {limit} profiles (the PRD "
                    f"limit). Delete one before enrolling '{str(name).strip()}'.",
                    code="auth_profile_limit",
                )
            self._write_arrays(modality, key, arrays)
            entry = {**meta, "name": str(name).strip(), "samples": len(arrays)}
            profiles[key] = entry
            self._write_index(index)
        return key, entry

    def load(self, modality: str, slug: str) -> list[np.ndarray]:
        path = self.directory / modality / f"{slug}.npz"
        try:
            with np.load(path) as archive:
                arrays = [
                    np.asarray(archive[key], dtype=np.float32) for key in sorted(archive.files)
                ]
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            logger.warning("biometrics_template_unreadable path=%s error=%s", path, exc)
            return []
        return [array for array in arrays if array.size]

    def delete(self, modality: str, name: str) -> bool:
        found = self.find(modality, name)
        if found is None:
            return False
        key, _entry = found
        with self._lock:
            index = self._read_index()
            index.get(modality, {}).pop(key, None)
            self._write_index(index)
        try:
            (self.directory / modality / f"{key}.npz").unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("biometric_template_not_removed error=%s", exc)
        return True

    def _write_arrays(self, modality: str, slug: str, arrays: list[np.ndarray]) -> None:
        target = self.directory / modality
        target.mkdir(parents=True, exist_ok=True)
        final = target / f"{slug}.npz"
        temp = target / f"{slug}.npz.tmp"
        payload = {
            f"t{index}": np.asarray(array, dtype=np.float32) for index, array in enumerate(arrays)
        }
        with open(temp, "wb") as handle:
            np.savez(handle, **payload)
        os.replace(temp, final)


# ------------------------------------------------------------------ gatekeeping
def require_factor(settings: Settings, modality: str) -> None:
    """Apply rails 1 and 2: the capability, then the security mode."""
    if modality not in MODALITIES:
        raise VisionError(
            f"Unknown authentication modality '{modality}'.", code="auth_bad_modality"
        )

    mode = settings.biometrics.mode
    if modality not in MODE_MODALITIES.get(mode, ()):
        raise VisionError(
            f"{MODALITY_LABELS[modality]} authentication is off — the security mode is "
            f"'{mode.replace('_', ' ')}'. Turn it on in Settings → Integrations → "
            "Authentication.",
            code="auth_mode_disabled",
        )

    decision = get_capabilities(settings).check("biometrics")
    if not decision.allowed:
        raise VisionError(
            f"{decision.reason}. Grant it in Settings → Tools → Permissions & capabilities.",
            code="auth_capability_denied",
        )


def require_hardware(settings: Settings, capability_id: str) -> None:
    """Rail 3: the device gate for the capture this call is about to make."""
    decision = get_capabilities(settings).check(capability_id)
    if not decision.allowed:
        raise VisionError(decision.reason, code=f"auth_{capability_id}_denied")


# ------------------------------------------------------------------ orchestration
def _voice_clip(
    settings: Settings,
    path: str | Path | None,
    duration_s: float | None,
) -> tuple[np.ndarray, str]:
    """The samples to compare: a file when one was given, otherwise the mic."""
    if path is not None:
        samples, label = load_wav(path)
    else:
        require_hardware(settings, "microphone")
        try:
            device, device_name = resolve_input_device(settings.voice.mic_device or None)
        except AudioError as exc:
            raise VisionError(str(exc), code="auth_mic_unavailable") from exc
        seconds = float(
            duration_s if duration_s is not None else settings.biometrics.voice_duration_s
        )
        samples = record_clip(seconds, device=device)
        label = device_name

    if rms(samples) < settings.voice.vad_threshold:
        raise VisionError(
            "That recording was silent — no voice was detected. Speak normally "
            "while it captures, or pass a WAV file with speech in it.",
            code="auth_no_speech",
        )
    return samples, label


def _face_source(settings: Settings, path: str | Path | None) -> tuple[Any, str]:
    """The picture to embed: a file when one was given, otherwise the webcam."""
    if path is not None:
        return decode_image(path)
    require_hardware(settings, "camera")
    vision = settings.vision
    frame = capture_frame(
        index=vision.camera_index,
        width=vision.camera_width,
        height=vision.camera_height,
        warmup_frames=vision.camera_warmup_frames,
    )
    return frame_to_image(frame), f"camera {vision.camera_index}"


def list_profiles(
    settings: Settings, modality: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Every enrolled profile, grouped by modality (for the card and the model)."""
    store = ProfileStore(settings)
    wanted = (modality,) if modality else MODALITIES
    return {name: store.list(name) for name in wanted}


def delete_profile(settings: Settings, modality: str, name: str) -> bool:
    """Forget one profile (PRD §27 "configured" implies it can be un-configured)."""
    if modality not in MODALITIES:
        raise VisionError(
            f"Unknown authentication modality '{modality}'.", code="auth_bad_modality"
        )
    return ProfileStore(settings).delete(modality, name)


async def enroll_voice(
    settings: Settings,
    name: str,
    *,
    path: str | Path | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Capture a voice clip and store it as ``name``'s voiceprint."""
    require_factor(settings, "voice")
    return await _run_blocking(_enroll_voice_sync, settings, str(name), path, duration_s)


async def verify_voice(
    settings: Settings,
    name: str | None = None,
    *,
    path: str | Path | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Compare a fresh clip against a stored voiceprint (or all of them)."""
    require_factor(settings, "voice")
    return await _run_blocking(_verify_voice_sync, settings, name, path, duration_s)


async def enroll_face(
    settings: Settings,
    name: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Detect a face and store its embedding as ``name``'s faceprint."""
    require_factor(settings, "face")
    return await _run_blocking(_enroll_face_sync, settings, str(name), path)


async def verify_face(
    settings: Settings,
    name: str | None = None,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare a fresh face against a stored faceprint (or all of them)."""
    require_factor(settings, "face")
    return await _run_blocking(_verify_face_sync, settings, name, path)


async def _run_blocking(function: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    """Run the capturing/number-crunching half off the event loop."""
    import asyncio  # noqa: PLC0415

    return await asyncio.to_thread(function, *args)


# ------------------------------------------------------------------ voice (sync)
def _enroll_voice_sync(
    settings: Settings,
    name: str,
    path: str | Path | None,
    duration_s: float | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    samples, source = _voice_clip(settings, path, duration_s)
    features = voice_features(samples)
    if features.shape[0] < 5:
        raise VisionError(
            "That clip is too short to be a voiceprint — hold the recording for "
            "a couple of seconds.",
            code="auth_no_speech",
        )
    key, entry = ProfileStore(settings).save(
        "voice",
        name,
        [features],
        {
            "enrolled_at": _now(),
            "source": source,
            "duration_s": round(float(samples.size) / TARGET_RATE, 2),
            "rate": TARGET_RATE,
            "frames": int(features.shape[0]),
        },
    )
    return {
        "modality": "voice",
        "name": entry["name"],
        "slug": key,
        "source": source,
        "frames": int(features.shape[0]),
        "duration_s": round(float(samples.size) / TARGET_RATE, 2),
        "enrolled_at": entry["enrolled_at"],
        "profiles": ProfileStore(settings).count("voice"),
        "message": f"Voice profile '{entry['name']}' enrolled.",
        "elapsed_ms": _ms(started),
    }


def _verify_voice_sync(
    settings: Settings,
    name: str | None,
    path: str | Path | None,
    duration_s: float | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    samples, source = _voice_clip(settings, path, duration_s)
    features = voice_features(samples)
    if features.shape[0] < 5:
        raise VisionError(
            "That clip is too short to identify anyone — speak for a couple of seconds.",
            code="auth_no_speech",
        )
    threshold = settings.biometrics.voice_threshold
    store = ProfileStore(settings)
    candidates = _candidates(store, "voice", name)
    if not candidates:
        raise VisionError(
            "No voice profiles are enrolled yet — say `enroll my voice` first.",
            code="auth_no_profile",
        )

    scored: list[dict[str, Any]] = []
    for slug, entry in candidates:
        templates = store.load("voice", slug)
        if not templates:
            continue
        best = max(voice_similarity(features, template) for template in templates)
        scored.append({"name": entry.get("name", slug), "slug": slug, "score": round(best, 4)})
    if not scored:
        raise VisionError(
            "The stored voiceprint could not be read — enroll that profile again.",
            code="auth_no_profile",
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    best = scored[0]
    return {
        "modality": "voice",
        "matched": bool(best["score"] >= threshold),
        "score": best["score"],
        "threshold": threshold,
        "profile": best["name"] if best["score"] >= threshold else None,
        "candidates": scored,
        "source": source,
        "message": _verdict("Voice", best, threshold, name),
        "elapsed_ms": _ms(started),
    }


# ------------------------------------------------------------------ face (sync)
def _enroll_face_sync(
    settings: Settings,
    name: str,
    path: str | Path | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    source_image, source = _face_source(settings, path)
    face = face_embedding(settings, source_image, label=source)
    key, entry = ProfileStore(settings).save(
        "face",
        name,
        [face["embedding"]],
        {
            "enrolled_at": _now(),
            "source": face["source"],
            "detection_score": face["score"],
        },
    )
    return {
        "modality": "face",
        "name": entry["name"],
        "slug": key,
        "source": face["source"],
        "detection_score": face["score"],
        "enrolled_at": entry["enrolled_at"],
        "profiles": ProfileStore(settings).count("face"),
        "message": f"Face profile '{entry['name']}' enrolled.",
        "elapsed_ms": _ms(started),
    }


def _verify_face_sync(
    settings: Settings,
    name: str | None,
    path: str | Path | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    source_image, source = _face_source(settings, path)
    face = face_embedding(settings, source_image, label=source)
    threshold = settings.biometrics.face_threshold
    store = ProfileStore(settings)
    candidates = _candidates(store, "face", name)
    if not candidates:
        raise VisionError(
            "No face profiles are enrolled yet — `enroll my face` first.",
            code="auth_no_profile",
        )

    recognizer = face["recognizer"]
    scored: list[dict[str, Any]] = []
    for slug, entry in candidates:
        templates = store.load("face", slug)
        if not templates:
            continue
        best = max(
            face_similarity(face["embedding"], template, recognizer) for template in templates
        )
        scored.append({"name": entry.get("name", slug), "slug": slug, "score": round(best, 4)})
    if not scored:
        raise VisionError(
            "The stored faceprint could not be read — enroll that profile again.",
            code="auth_no_profile",
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    best = scored[0]
    return {
        "modality": "face",
        "matched": bool(best["score"] >= threshold),
        "score": best["score"],
        "threshold": threshold,
        "profile": best["name"] if best["score"] >= threshold else None,
        "candidates": scored,
        "source": source,
        "detection_score": face["score"],
        "message": _verdict("Face", best, threshold, name),
        "elapsed_ms": _ms(started),
    }


# ---------------------------------------------------------------------- helpers
def _candidates(
    store: ProfileStore, modality: str, name: str | None
) -> list[tuple[str, dict[str, Any]]]:
    """The profiles to score against: one when named, all of them otherwise."""
    if name:
        found = store.find(modality, name)
        if found is None:
            raise VisionError(
                f"No {modality} profile named '{name}' is enrolled.",
                code="auth_no_profile",
            )
        return [found]
    return store.items(modality)


def _verdict(label: str, best: dict[str, Any], threshold: float, wanted: str | None) -> str:
    who = f"'{best['name']}'" if best["score"] >= threshold else "an enrolled profile"
    tail = f" against '{wanted}'" if wanted else ""
    if best["score"] >= threshold:
        return f"{label} matched {who} ({best['score']:.3f} ≥ {threshold:.3f}{tail})."
    return f"{label} did not match {who} (best {best['score']:.3f} < {threshold:.3f}{tail})."


def _now() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC).isoformat(timespec="seconds")


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def auth_status(settings: Settings) -> dict[str, Any]:
    """Everything the Settings card needs, without touching a device.

    The two model flags are *presence* checks: downloading 37 MB as a side
    effect of opening Settings would be rude, and lighting the camera would be
    worse.
    """
    capabilities = get_capabilities(settings)
    ready = models_ready(settings)
    return {
        "mode": settings.biometrics.mode,
        "max_profiles": settings.biometrics.max_profiles,
        "biometrics": capabilities.check("biometrics").model_dump(),
        "microphone": capabilities.check("microphone").model_dump(),
        "camera": capabilities.check("camera").model_dump(),
        "opencv_available": opencv_available(),
        "face_api": face_api_available(),
        "models": ready,
        "models_ready": all(ready.values()),
        "profiles": {modality: ProfileStore(settings).count(modality) for modality in MODALITIES},
    }


__all__ = [
    "FEATURE_DIM",
    "MODALITIES",
    "MODE_MODALITIES",
    "MODEL_SPECS",
    "Modality",
    "ProfileStore",
    "auth_status",
    "delete_profile",
    "dtw_distance",
    "enroll_face",
    "enroll_voice",
    "ensure_model",
    "face_api_available",
    "face_embedding",
    "face_similarity",
    "list_profiles",
    "load_wav",
    "mfcc",
    "model_path",
    "models_ready",
    "record_clip",
    "require_factor",
    "require_hardware",
    "reset_face_models",
    "reset_recorder",
    "set_recorder",
    "verify_face",
    "verify_voice",
    "voice_features",
    "voice_similarity",
]
