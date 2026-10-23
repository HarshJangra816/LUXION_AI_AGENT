"""Authentication status + settings + live actions (PRD §27, §28, Phase 11c).

``GET    /auth``                  effective policy + defaults + status (card)
``PUT    /auth/config``           persist Settings → Authentication (overlay)
``DELETE /auth/config``           back to ``.env`` defaults
``GET    /auth/profiles``         every enrolled voice/face profile
``DELETE /auth/profiles/{m}/{n}`` forget one profile
``POST   /auth/enroll``           capture a clip/frame and store a profile
``POST   /auth/verify``           capture a clip/frame and score it

The two POSTs run exactly the code the tools run, so the card can prove the
family works — an unverifiable biometric is a silent failure otherwise. They
are opt-in buttons, never automatic: nothing here opens the microphone or the
camera as a side effect of loading Settings, and every call applies the same
three rails as the tools (``biometrics`` capability → security mode → the
device gate for the capture it is about to make).
"""

from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from luxion.config.biometrics_override import clear_overrides
from luxion.config.settings import (
    BiometricsConfig,
    Settings,
    get_settings,
    reset_settings_cache,
    save_biometrics_overrides,
)
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.vision import auth as biometrics
from luxion.vision.imaging import VisionError

router = APIRouter(prefix="/auth", tags=["authentication"])

MODALITIES = ("voice", "face")

MODE_LABELS = {
    "disabled": "Disabled",
    "voice_only": "Voice only",
    "face_only": "Face only",
    "voice_face": "Voice + Face",
}


class AuthConfigBundle(BaseModel):
    """What Settings → Authentication edits (effective values + defaults)."""

    config: BiometricsConfig
    defaults: BiometricsConfig
    status: dict[str, Any]
    catalog: dict[str, Any]


class AuthConfigPatch(BaseModel):
    """Partial authentication policy — mirrors every ``BiometricsConfig`` field.

    All fields optional so the card can PATCH just what changed; a test keeps
    this in sync with :class:`luxion.config.settings.BiometricsConfig` so a
    new knob can never be silently unwritable from the UI.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    voice_duration_s: float | None = None
    voice_threshold: float | None = None
    face_threshold: float | None = None
    max_profiles: int | None = None

    def values(self) -> dict[str, Any]:
        return dict(self.model_dump(exclude_none=True))


class ProfilesOut(BaseModel):
    """Every enrolled profile, grouped by modality."""

    voice: list[dict[str, Any]] = []
    face: list[dict[str, Any]] = []


class ProfileDeletedOut(BaseModel):
    modality: str
    name: str
    deleted: bool


class AuthActionRequest(BaseModel):
    """One enrollment or verification (the tools accept the same arguments)."""

    model_config = ConfigDict(extra="forbid")

    modality: Literal["voice", "face"]
    #: Profile to enroll (required) or to verify against (optional — omit it
    #: and every enrolled profile of that modality is scored).
    name: str | None = None
    #: File instead of the hardware: a WAV for voice, an image for face.
    path: str | None = None
    #: Seconds of speech to capture (voice only).
    duration_s: float | None = Field(default=None, ge=1.0, le=15.0)


class AuthOutcome(BaseModel):
    """A heterogeneous result: enrollment and verification report different
    fields, so each one is optional and ``modality``/``message`` carry the
    common part."""

    modality: str
    message: str

    # enrollment
    name: str | None = None
    slug: str | None = None
    enrolled_at: str | None = None
    profiles: int | None = None
    frames: int | None = None
    duration_s: float | None = None

    # verification
    matched: bool | None = None
    score: float | None = None
    threshold: float | None = None
    profile: str | None = None
    candidates: list[dict[str, Any]] = []

    # both
    source: str | None = None
    detection_score: float | None = None
    elapsed_ms: int = 0


def _bundle() -> AuthConfigBundle:
    settings = get_settings()
    return AuthConfigBundle(
        config=settings.biometrics,
        defaults=BiometricsConfig(),
        status=biometrics.auth_status(settings),
        catalog=_catalog(),
    )


def _catalog() -> dict[str, Any]:
    return {
        "modes": [{"value": value, "label": MODE_LABELS[value]} for value in MODE_LABELS],
        "modalities": list(MODALITIES),
        "max_profiles": BiometricsConfig().max_profiles,
        "duration_range": [1.0, 15.0],
        "threshold_range": [0.0, 1.0],
        # The models are Apache-2.0 opencv_zoo files, fetched once on first use
        # into <data_dir>/vision_models/ — never on Settings load.
        "models": [
            {"id": name, "filename": spec.filename, "url": spec.url}
            for name, spec in biometrics.MODEL_SPECS.items()
        ],
    }


def _fail(exc: VisionError) -> NoReturn:
    """A denial is 403 (policy/consent); anything the caller can fix is 400."""
    status = 403 if exc.code.endswith("_denied") or exc.code == "auth_mode_disabled" else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _target(path: str | None, settings: Settings) -> str | None:
    """Resolve an optional file argument the same way the tool does."""
    if not path:
        return None
    try:
        return str(resolve_in_workspace(path, ToolContext(settings)))
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=AuthConfigBundle)
async def read_auth() -> AuthConfigBundle:
    return _bundle()


@router.put("/config", response_model=AuthConfigBundle)
async def write_auth(patch: AuthConfigPatch) -> AuthConfigBundle:
    settings = get_settings()
    try:
        save_biometrics_overrides(settings, patch.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bundle()


@router.delete("/config", response_model=AuthConfigBundle)
async def reset_auth() -> AuthConfigBundle:
    settings = get_settings()
    clear_overrides(settings.app.data_dir)
    reset_settings_cache()
    return _bundle()


@router.get("/profiles", response_model=ProfilesOut)
async def read_profiles() -> ProfilesOut:
    settings = get_settings()
    grouped = biometrics.list_profiles(settings)
    return ProfilesOut(voice=grouped.get("voice", []), face=grouped.get("face", []))


@router.delete("/profiles/{modality}/{name}", response_model=ProfileDeletedOut)
async def delete_profile(modality: str, name: str) -> ProfileDeletedOut:
    settings = get_settings()
    if modality not in MODALITIES:
        raise HTTPException(status_code=404, detail=f"Unknown modality '{modality}'.")
    try:
        deleted = biometrics.delete_profile(settings, modality, name)
    except VisionError as exc:
        _fail(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No {modality} profile named '{name}'.")
    return ProfileDeletedOut(modality=modality, name=name, deleted=True)


@router.post("/enroll", response_model=AuthOutcome)
async def enroll(request: AuthActionRequest) -> AuthOutcome:
    """Capture a clip or a frame and store it as a profile."""
    settings = get_settings()
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Pass a 'name' for the profile.")
    target = _target(request.path, settings)
    try:
        if request.modality == "voice":
            result = await biometrics.enroll_voice(
                settings, name, path=target, duration_s=request.duration_s
            )
        else:
            result = await biometrics.enroll_face(settings, name, path=target)
    except VisionError as exc:
        _fail(exc)
    return AuthOutcome(**result)


@router.post("/verify", response_model=AuthOutcome)
async def verify(request: AuthActionRequest) -> AuthOutcome:
    """Score a fresh clip or frame against the stored profiles."""
    settings = get_settings()
    name = (request.name or "").strip() or None
    target = _target(request.path, settings)
    try:
        if request.modality == "voice":
            result = await biometrics.verify_voice(
                settings, name, path=target, duration_s=request.duration_s
            )
        else:
            result = await biometrics.verify_face(settings, name, path=target)
    except VisionError as exc:
        _fail(exc)
    return AuthOutcome(**result)
