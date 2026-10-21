"""Send an image to the configured vision model (PRD §5.9, §33.15, Phase 11).

The vision family reuses the **existing** provider contract — no new Python
dependency and no second LLM stack. ``ChatMessage.images`` carries the
picture; the Ollama provider sends it as ``images[]`` and the
OpenAI-compatible provider as an ``image_url`` content part.

A deployment usually wants a *different* model for seeing than for talking
(a local ``qwen2.5vl:3b`` next to a cloud chat model, say), so
:func:`resolve_vision_llm` derives the endpoint/model pair from
:class:`~luxion.config.settings.VisionConfig`.
"""

from __future__ import annotations

from typing import Any

from luxion.config.settings import OLLAMA_BASE_URL, Settings
from luxion.llm.registry import create_provider, get_provider
from luxion.llm.types import ChatMessage
from luxion.vision.imaging import PreparedImage, VisionError


def resolve_vision_llm(settings: Settings) -> tuple[Any, str]:
    """Return ``(llm config, model id)`` the vision calls should use.

    The config is the chat config with the vision overrides applied; the
    model id is the vision model when set, otherwise the chat model (which
    may still be empty — the caller resolves it against the endpoint).
    """
    llm = settings.llm
    vision = settings.vision
    updates: dict[str, object] = {}

    provider = vision.provider.strip()
    if provider and provider != llm.provider:
        updates["provider"] = provider
        if provider == "ollama":
            # Ollama always talks to its own local port.
            updates["base_url"] = OLLAMA_BASE_URL

    base_url = vision.base_url.strip()
    if base_url:
        updates["base_url"] = base_url

    api_key_env = vision.api_key_env.strip()
    if api_key_env:
        updates["api_key_env"] = api_key_env

    # The vision family gets its own HTTP budget.
    updates["request_timeout_s"] = vision.timeout_s

    resolved = llm.model_copy(update=updates)
    model = vision.model.strip() or llm.model
    return resolved, model


def vision_provider(settings: Settings) -> Any:
    """The provider instance the vision calls should use.

    Reuses the registry cache so the HTTP client (and its connection pool)
    is shared with the chat path when the endpoint is the same.
    """
    config, _ = resolve_vision_llm(settings)
    return get_provider(config)


def build_prompt(question: str | None, images: list[PreparedImage]) -> str:
    """The user turn: the question, plus a note about how many images."""
    instruction = (question or "").strip()
    if not instruction:
        instruction = "Describe this image in detail."
    if len(images) > 1:
        instruction = f"{instruction}\n\n(The {len(images)} images are in the order given.)"
    return instruction


async def analyze_images(
    settings: Settings,
    images: list[PreparedImage],
    *,
    question: str | None = None,
) -> str:
    """Ask the vision model about ``images`` and return its answer.

    Raises :class:`~luxion.vision.imaging.VisionError` when vision is
    disabled, no image was given, or the provider call fails.
    """
    if not settings.vision.enabled:
        raise VisionError(
            "Vision is turned off. Enable it in Settings → Vision to let Luxion look at images.",
            code="vision_disabled",
        )
    if not images:
        raise VisionError("No image was supplied.", code="vision_no_image")

    config, model = resolve_vision_llm(settings)
    provider = get_provider(config)
    if not model:
        try:
            model = await provider.resolve_model()
        except Exception as exc:  # noqa: BLE001 - provider errors are LLMError
            raise VisionError(
                f"Could not resolve a vision model: {exc}",
                code="vision_no_model",
            ) from exc

    message = ChatMessage(
        role="user",
        content=build_prompt(question, images),
        images=[image.as_payload() for image in images],
    )
    try:
        result = await provider.complete(
            [message],
            model=model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )
    except VisionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface provider errors as tool errors
        raise VisionError(f"Vision model call failed: {exc}", code="vision_call_failed") from exc

    text = (result.text or "").strip()
    if not text:
        raise VisionError(
            f"The vision model '{model}' returned an empty answer.",
            code="vision_empty_answer",
        )
    return text


async def probe_vision(settings: Settings) -> dict[str, Any]:
    """Check that the vision endpoint is reachable and knows the model.

    Cheap on purpose: it lists the models and looks for the configured one.
    It does **not** spend a vision call.
    """
    config, model = resolve_vision_llm(settings)
    provider = get_provider(config)
    try:
        models = await provider.list_models()
    except Exception as exc:  # noqa: BLE001 - provider errors are LLMError
        return {
            "ok": False,
            "provider": config.provider,
            "model": model,
            "models": [],
            "error": str(exc),
        }
    resolved = model or (models[0] if models else "")
    return {
        "ok": True,
        "provider": config.provider,
        "model": resolved,
        "models": models,
        "error": None,
        # An empty list means the endpoint did not enumerate its models.
        "found": (not models) or (resolved in models),
    }


__all__ = [
    "analyze_images",
    "build_prompt",
    "create_provider",
    "probe_vision",
    "resolve_vision_llm",
    "vision_provider",
]
