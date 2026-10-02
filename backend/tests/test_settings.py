from pathlib import Path

import pytest
from pydantic import ValidationError

from luxion.config.settings import SecurityConfig, Settings, get_settings, reset_settings_cache


def test_defaults_are_sane() -> None:
    settings = get_settings()
    assert settings.server.port == 8756
    assert settings.server.host == "127.0.0.1"
    assert 0 <= settings.security.autonomy_level <= 5
    assert settings.db.url.startswith("sqlite:///")
    assert settings.context.total_budget_tokens > settings.context.reserve_tokens


def test_nested_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUXION_SERVER__PORT", "9999")
    monkeypatch.setenv("LUXION_LLM__PROVIDER", "openai")
    reset_settings_cache()
    try:
        settings = get_settings()
        assert settings.server.port == 9999
        assert settings.llm.provider == "openai"
    finally:
        reset_settings_cache()


def test_db_url_derived_from_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUXION_DB__URL", raising=False)
    reset_settings_cache()
    try:
        settings = Settings(db={"url": ""}, app={"data_dir": "D:/LuxionData"})
        assert settings.db.url == "sqlite:///D:/LuxionData/luxion.db"
    finally:
        reset_settings_cache()


def test_autonomy_level_bounds() -> None:
    with pytest.raises(ValidationError):
        SecurityConfig(autonomy_level=7)
    with pytest.raises(ValidationError):
        SecurityConfig(autonomy_level=-1)


def test_workspaces_string_parsing() -> None:
    cfg = SecurityConfig(allowed_workspaces="D:/Projects;D:/Luxion")
    assert cfg.allowed_workspaces == [Path("D:/Projects"), Path("D:/Luxion")]


def test_empty_workspaces_fall_back_to_the_project_root() -> None:
    from luxion.config.settings import PROJECT_ROOT

    # `LUXION_SECURITY__ALLOWED_WORKSPACES=` in a copied .env must not lock
    # every file tool out.
    assert SecurityConfig(allowed_workspaces="").allowed_workspaces == [PROJECT_ROOT]
    assert SecurityConfig(allowed_workspaces=" ; ").allowed_workspaces == [PROJECT_ROOT]
