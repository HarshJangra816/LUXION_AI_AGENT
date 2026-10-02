"""Settings-page provider switching (tap an adapter → active immediately)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from luxion.config.provider_override import (
    FILE_NAME,
    ProviderSelection,
    clear_selection,
    load_selection,
    save_selection,
    selection_path,
)
from luxion.config.settings import (
    OLLAMA_BASE_URL,
    SELECTABLE_PROVIDERS,
    get_settings,
    reset_settings_cache,
)


@pytest.fixture(autouse=True)
def clean_selection():
    """Every test starts (and ends) with no persisted provider selection."""
    data_dir = get_settings().app.data_dir
    clear_selection(data_dir)
    reset_settings_cache()
    yield
    clear_selection(data_dir)
    reset_settings_cache()


# --------------------------------------------------------------------- store
def test_missing_selection_reads_as_none(tmp_path: Path) -> None:
    assert load_selection(tmp_path) is None
    assert clear_selection(tmp_path) is False


def test_selection_round_trip(tmp_path: Path) -> None:
    selection = ProviderSelection(active="openrouter", models={"openrouter": "a/b"})
    saved = save_selection(tmp_path, selection)

    assert saved == tmp_path / FILE_NAME
    assert saved.is_file()
    assert load_selection(tmp_path) == selection


def test_corrupt_selection_is_ignored(tmp_path: Path) -> None:
    path = selection_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    assert load_selection(tmp_path) is None


def test_selection_written_with_a_utf8_bom_still_loads(tmp_path: Path) -> None:
    # PowerShell 5.1's `Set-Content -Encoding utf8` writes a BOM.
    path = selection_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ProviderSelection(active="ollama").model_dump_json().encode()
    path.write_bytes(b"\xef\xbb\xbf" + body)

    assert load_selection(tmp_path) == ProviderSelection(active="ollama")


def test_clear_removes_the_file(tmp_path: Path) -> None:
    save_selection(tmp_path, ProviderSelection(active="ollama"))
    assert clear_selection(tmp_path) is True
    assert load_selection(tmp_path) is None


# ------------------------------------------------------------------ settings
def test_selectable_providers_match_the_registry() -> None:
    from luxion.llm.registry import PROVIDER_TYPES

    assert set(PROVIDER_TYPES) == SELECTABLE_PROVIDERS


def test_no_selection_keeps_env_defaults() -> None:
    settings = get_settings()

    assert settings.llm.provider == "mock"  # LUXION_LLM__PROVIDER from conftest
    assert settings.llm.base_url == OLLAMA_BASE_URL


def test_selection_overrides_provider_and_base_url() -> None:
    save_selection(get_settings().app.data_dir, ProviderSelection(active="ollama"))
    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.provider == "ollama"
    # Local adapters keep the .env endpoint (it already points at Ollama).
    assert settings.llm.base_url == OLLAMA_BASE_URL


def test_cloud_adapter_gets_its_own_endpoint_and_auto_model() -> None:
    save_selection(get_settings().app.data_dir, ProviderSelection(active="openrouter"))
    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.provider == "openrouter"
    # Empty = OpenRouter's own default, never the local Ollama URL.
    assert settings.llm.base_url == ""
    # Model ids do not transfer between providers → auto-detect.
    assert settings.llm.model == ""


def test_openai_adapter_points_at_the_real_api() -> None:
    save_selection(get_settings().app.data_dir, ProviderSelection(active="openai"))
    reset_settings_cache()

    assert get_settings().llm.base_url == "https://api.openai.com/v1"


def test_saved_model_wins_over_env_model() -> None:
    save_selection(
        get_settings().app.data_dir,
        ProviderSelection(active="mock", models={"mock": "mock-custom"}),
    )
    reset_settings_cache()

    assert get_settings().llm.model == "mock-custom"


def test_env_model_is_seeded_when_the_env_provider_was_never_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUXION_LLM__MODEL", "env-model")
    save_selection(get_settings().app.data_dir, ProviderSelection(active="mock"))
    reset_settings_cache()

    # `.env` configured this adapter → it keeps its configured model.
    assert get_settings().llm.model == "env-model"

    # An adapter `.env` does not describe auto-detects instead.
    selection = load_selection(get_settings().app.data_dir)
    assert selection is not None
    selection.active = "ollama"
    save_selection(get_settings().app.data_dir, selection)
    reset_settings_cache()
    assert get_settings().llm.model == ""


def test_unknown_provider_in_the_file_falls_back_to_env() -> None:
    save_selection(get_settings().app.data_dir, ProviderSelection(active="gpt5"))
    reset_settings_cache()

    assert get_settings().llm.provider == "mock"


def test_saved_base_url_for_custom_endpoint_is_not_recomputed() -> None:
    # `openai_compatible` reads its endpoint from .env (SELECTED_BASE_URLS → None).
    save_selection(get_settings().app.data_dir, ProviderSelection(active="openai_compatible"))
    reset_settings_cache()

    assert get_settings().llm.base_url == OLLAMA_BASE_URL


# ---------------------------------------------------------------------- API
def test_put_switches_the_active_adapter(client: TestClient) -> None:
    response = client.put("/api/llm/provider", json={"provider": "ollama"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["label"] == "Ollama (local)"
    # The choice survives a settings rebuild (i.e. a backend restart).
    assert client.get("/api/llm/status").json()["provider"] == "ollama"
    assert load_selection(get_settings().app.data_dir) is not None


def test_put_can_set_the_model_in_the_same_call(client: TestClient) -> None:
    response = client.put("/api/llm/provider", json={"provider": "ollama", "model": "llama3.2"})

    assert response.status_code == 200
    assert response.json()["model"] == "llama3.2"


def test_model_is_kept_when_the_adapter_is_switched_back(client: TestClient) -> None:
    client.put("/api/llm/provider", json={"provider": "ollama", "model": "llama3.2"})
    client.put("/api/llm/provider", json={"provider": "mock"})
    body = client.put("/api/llm/provider", json={"provider": "ollama"}).json()

    assert body["model"] == "llama3.2"


def test_put_rejects_an_unknown_adapter(client: TestClient) -> None:
    response = client.put("/api/llm/provider", json={"provider": "nope"})

    assert response.status_code == 400
    assert "Unknown provider" in response.json()["detail"]
    # Nothing was persisted and the active adapter did not move.
    assert client.get("/api/llm/status").json()["provider"] == "mock"


def test_put_requires_a_provider(client: TestClient) -> None:
    assert client.put("/api/llm/provider", json={}).status_code == 422
    assert client.put("/api/llm/provider", json={"provider": ""}).status_code == 422


def test_delete_falls_back_to_env(client: TestClient) -> None:
    client.put("/api/llm/provider", json={"provider": "ollama", "model": "llama3.2"})

    response = client.delete("/api/llm/provider")

    assert response.status_code == 200
    assert response.json()["provider"] == "mock"
    assert client.get("/api/llm/status").json()["model"] == ""
    assert load_selection(get_settings().app.data_dir) is None


def test_status_lists_every_selectable_adapter(client: TestClient) -> None:
    body = client.get("/api/llm/status").json()

    assert {spec["id"] for spec in body["available_providers"]} == set(SELECTABLE_PROVIDERS)


def test_selection_file_holds_no_secrets(client: TestClient) -> None:
    client.put("/api/llm/provider", json={"provider": "openrouter", "model": "a/b"})
    path = selection_path(get_settings().app.data_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"active", "models"}
    assert "api_key" not in path.read_text(encoding="utf-8")
