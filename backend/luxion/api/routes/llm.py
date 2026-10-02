"""LLM configuration visibility + runtime switching for the Settings page."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from luxion.api.schemas import LLMStatus, build_llm_status
from luxion.config.provider_override import (
    ProviderSelection,
    clear_selection,
    load_selection,
    save_selection,
)
from luxion.config.settings import SELECTABLE_PROVIDERS, get_settings, reset_settings_cache
from luxion.llm.base import ProviderHealth
from luxion.llm.registry import aclose_provider, provider_health

router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderSwitch(BaseModel):
    """Body of ``PUT /llm/provider`` — switch adapter, optionally set its model."""

    provider: str = Field(min_length=1, max_length=64)
    #: ``None`` keeps whatever the adapter already had (including no entry,
    #: which means "auto-detect"); ``""`` clears a previously saved model.
    model: str | None = Field(default=None, max_length=255)


async def _rebuild_status() -> LLMStatus:
    """Close the live provider, drop the settings cache, report the new state."""
    await aclose_provider()
    reset_settings_cache()
    return build_llm_status(get_settings())


@router.get("/status", response_model=LLMStatus)
def llm_status() -> LLMStatus:
    return build_llm_status(get_settings())


@router.get("/health", response_model=ProviderHealth)
async def llm_health() -> ProviderHealth:
    return await provider_health(get_settings().llm)


@router.put("/provider", response_model=LLMStatus)
async def switch_provider(body: ProviderSwitch) -> LLMStatus:
    """Make an installed adapter active (Settings → tap an adapter)."""
    provider = body.provider.strip()
    if provider not in SELECTABLE_PROVIDERS:
        known = ", ".join(sorted(SELECTABLE_PROVIDERS))
        raise HTTPException(
            status_code=400, detail=f"Unknown provider '{provider}'. Known: {known}."
        )

    settings = get_settings()
    selection = load_selection(settings.app.data_dir) or ProviderSelection(
        active=settings.llm.provider
    )
    if body.model is not None:
        selection.models[provider] = body.model.strip()
    selection.active = provider
    save_selection(settings.app.data_dir, selection)
    return await _rebuild_status()


@router.delete("/provider", response_model=LLMStatus)
async def reset_provider_selection() -> LLMStatus:
    """Forget the Settings-page choice and fall back to ``.env``."""
    clear_selection(get_settings().app.data_dir)
    return await _rebuild_status()
