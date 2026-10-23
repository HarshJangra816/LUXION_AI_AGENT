"""Authentication tools: the voiceprint and faceprint second factors (Phase 11c).

Four tools, two per modality (PRD §27 voice, §28 face):

=================  ==========================================  ============
Tool               Does                                        Risk
=================  ==========================================  ============
``enroll_voice``   learn a speaker's voice from a clip         medium
``verify_voice``   say whether a fresh clip is that speaker    low, read-only
``enroll_face``    learn a face from the webcam or a photo     medium
``verify_face``    say whether a fresh face is that person     low, read-only
=================  ==========================================  ============

All four declare ``requires="biometrics"`` — an app consent that ships **OFF**
(PRD §39), so the executor blocks them before the risk engine even runs. The
hardware gate for the capture itself (``microphone`` / ``camera``) is checked
inside :mod:`luxion.vision.auth`, because a tool may declare only one
capability.

Enrollment replaces the profile of the same name and refuses past the PRD's
five-profile cap; verification without a ``name`` scores *every* enrolled
profile and reports the best one — that is the §27 "who said it?" answer.
"""

from __future__ import annotations

from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace
from luxion.vision import auth as biometrics
from luxion.vision.imaging import VisionError

#: Common category so the tool router and the system prompt recognise the
#: family at a glance.
CATEGORY = "biometrics"

_NAME_PROPERTY = {
    "type": "string",
    "description": (
        "Profile name to enroll or verify, e.g. 'harsh'. Verification may omit "
        "it to check the sample against every enrolled profile."
    ),
}
_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional file instead of the hardware: a WAV with speech for voice, an "
        "image containing one face for face. Must sit inside an approved workspace."
    ),
}


def _map(exc: VisionError) -> ToolError:
    """A vision/auth failure travels to the model with its machine code intact."""
    return ToolError(str(exc), code=exc.code)


def _resolve(raw: object, ctx: ToolContext) -> str | None:
    if not raw:
        return None
    return str(resolve_in_workspace(str(raw), ctx))


def _duration(args: dict) -> float | None:
    raw = args.get("duration_s")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("duration_s must be a number of seconds", code="invalid_arguments") from exc
    if not 1.0 <= seconds <= 15.0:
        raise ToolError("duration_s must be between 1 and 15 seconds", code="invalid_arguments")
    return seconds


class EnrollVoice(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="enroll_voice",
            description=(
                "Teach Luxion a speaker's voice: records a few seconds of speech "
                "(or reads a WAV file) and stores it as a voice profile for later "
                "`verify_voice` checks. Say what it is doing and how long it will "
                "take — the microphone stays open for the whole clip. Replaces the "
                "profile of the same name; five profiles maximum."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "voice",
                "speaker",
                "voiceprint",
                "enroll",
                "enrol",
                "register",
                "profile",
                "authentication",
                "verify",
                "identify",
                "learn",
            ],
            read_only=False,
            requires="biometrics",
            parameters={
                "type": "object",
                "properties": {
                    "name": _NAME_PROPERTY,
                    "path": _PATH_PROPERTY,
                    "duration_s": {
                        "type": "number",
                        "description": "Seconds of speech to capture (1-15; from settings).",
                        "minimum": 1,
                        "maximum": 15,
                    },
                },
                "required": ["name"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ToolError("enroll_voice needs a 'name' for the profile", code="invalid_arguments")
        try:
            outcome = await biometrics.enroll_voice(
                ctx.settings,
                name,
                path=_resolve(args.get("path"), ctx),
                duration_s=_duration(args),
            )
        except VisionError as exc:
            raise _map(exc) from exc
        return ToolResult(
            output=(
                f"{outcome['message']} Captured {outcome['duration_s']}s from "
                f"{outcome['source']} ({outcome['frames']} frames)."
            ),
            data=outcome,
        )


class VerifyVoice(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="verify_voice",
            description=(
                "Ask whether a voice belongs to an enrolled profile: captures a few "
                "seconds of speech (or reads a WAV file) and compares it against the "
                "stored voiceprints. Omit 'name' to find out *who* is speaking — the "
                "best-scoring profile wins. Speech recognition answers what was said; "
                "this answers who said it."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "voice",
                "speaker",
                "voiceprint",
                "verify",
                "authentication",
                "identity",
                "who",
                "profile",
                "match",
                "recognise",
                "recognize",
            ],
            read_only=True,
            requires="biometrics",
            parameters={
                "type": "object",
                "properties": {
                    "name": _NAME_PROPERTY,
                    "path": _PATH_PROPERTY,
                    "duration_s": {
                        "type": "number",
                        "description": "Seconds of speech to capture (1-15; from settings).",
                        "minimum": 1,
                        "maximum": 15,
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args.get("name") or "").strip() or None
        try:
            outcome = await biometrics.verify_voice(
                ctx.settings,
                name,
                path=_resolve(args.get("path"), ctx),
                duration_s=_duration(args),
            )
        except VisionError as exc:
            raise _map(exc) from exc
        return ToolResult(output=outcome["message"], data=outcome)


class EnrollFace(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="enroll_face",
            description=(
                "Teach Luxion a face: opens the webcam (or reads an image file), "
                "detects the most confident face and stores its embedding as a face "
                "profile for later `verify_face` checks. One face must be visible in "
                "good light. Replaces the profile of the same name; five profiles "
                "maximum."
            ),
            risk="medium",
            category=CATEGORY,
            tags=[
                "face",
                "facial",
                "faceprint",
                "enroll",
                "enrol",
                "register",
                "profile",
                "authentication",
                "verify",
                "identify",
                "learn",
                "photo",
            ],
            read_only=False,
            requires="biometrics",
            parameters={
                "type": "object",
                "properties": {
                    "name": _NAME_PROPERTY,
                    "path": _PATH_PROPERTY,
                },
                "required": ["name"],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ToolError("enroll_face needs a 'name' for the profile", code="invalid_arguments")
        try:
            outcome = await biometrics.enroll_face(
                ctx.settings, name, path=_resolve(args.get("path"), ctx)
            )
        except VisionError as exc:
            raise _map(exc) from exc
        return ToolResult(
            output=(
                f"{outcome['message']} Face detected from {outcome['source']} "
                f"(confidence {outcome['detection_score']:.2f})."
            ),
            data=outcome,
        )


class VerifyFace(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="verify_face",
            description=(
                "Ask whether a face belongs to an enrolled profile: captures the "
                "webcam (or reads an image file) and compares the embedding against "
                "the stored faceprints. Omit 'name' to find out *who* is in frame — "
                "the best-scoring profile wins."
            ),
            risk="low",
            category=CATEGORY,
            tags=[
                "face",
                "facial",
                "faceprint",
                "verify",
                "authentication",
                "identity",
                "who",
                "profile",
                "match",
                "recognise",
                "recognize",
            ],
            read_only=True,
            requires="biometrics",
            parameters={
                "type": "object",
                "properties": {
                    "name": _NAME_PROPERTY,
                    "path": _PATH_PROPERTY,
                },
                "required": [],
            },
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        name = str(args.get("name") or "").strip() or None
        try:
            outcome = await biometrics.verify_face(
                ctx.settings, name, path=_resolve(args.get("path"), ctx)
            )
        except VisionError as exc:
            raise _map(exc) from exc
        return ToolResult(output=outcome["message"], data=outcome)


BUILTIN_TOOLS: list[Tool] = [EnrollVoice(), VerifyVoice(), EnrollFace(), VerifyFace()]

__all__ = [
    "BUILTIN_TOOLS",
    "CATEGORY",
    "EnrollFace",
    "EnrollVoice",
    "VerifyFace",
    "VerifyVoice",
]
