"""Settings → Memory config API: bundle, patch, reset (PRD §32, Phase 5d)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from luxion.api.routes.memory import RAGConfigPatch
from luxion.config import rag_override
from luxion.config.settings import (
    EMBEDDING_MODELS,
    RAGConfig,
    Settings,
    get_settings,
    reset_settings_cache,
)
from luxion.database.session import get_session_factory, init_db
from luxion.memory import store
from luxion.rag import vector_store
from luxion.rag.embeddings import reset_embedding_provider
from luxion.rag.models import Chunk
from luxion.repository.scanner import REPO_SOURCE_TYPES


@pytest.fixture()
def clean_rag(client: TestClient):  # noqa: ANN201
    """The shared data dir is suite-wide — keep rag.json hermetic per test."""
    init_db()
    data_dir = get_settings().app.data_dir
    rag_override.clear_overrides(data_dir)
    reset_settings_cache()
    _clear()
    yield client
    _clear()
    rag_override.clear_overrides(data_dir)
    reset_settings_cache()
    reset_embedding_provider()


def _clear() -> None:
    with get_session_factory()() as session:
        store.clear_memories(session)
        # Repo chunks leak between files otherwise, which would break the
        # ``chunks == 0`` health assertion above.
        sources = list(
            session.execute(
                select(Chunk.source).where(Chunk.source_type.in_(REPO_SOURCE_TYPES)).distinct()
            ).scalars()
        )
        for source in sources:
            vector_store.delete_source(session, source)
        session.commit()


# ------------------------------------------------------------------- bundle
def test_config_read_reports_defaults_and_health(clean_rag: TestClient) -> None:
    bundle = clean_rag.get("/api/memory/config").json()

    assert set(bundle) == {
        "config",
        "defaults",
        "needs_reembed",
        "chunks",
        "vectors",
        "embedding_models",
    }
    assert bundle["defaults"] == RAGConfig().model_dump()
    assert set(bundle["config"]) == set(RAGConfig.model_fields)
    assert bundle["needs_reembed"] is False
    assert bundle["chunks"] == 0
    assert [model["id"] for model in bundle["embedding_models"]] == [
        spec.id for spec in EMBEDDING_MODELS
    ]


def test_config_patch_covers_every_rag_knob() -> None:
    assert RAGConfigPatch.model_config.get("extra") == "forbid"
    assert set(RAGConfigPatch.model_fields) == set(RAGConfig.model_fields)
    for name, field in RAGConfigPatch.model_fields.items():
        assert "None" in str(field.annotation), f"{name} must accept None (partial patch)"


def test_config_patch_persists_and_merges(clean_rag: TestClient) -> None:
    first = clean_rag.put("/api/memory/config", json={"top_k": 9})
    assert first.status_code == 200
    assert first.json()["config"]["top_k"] == 9

    second = clean_rag.put("/api/memory/config", json={"min_score": 0.4})
    assert second.status_code == 200

    config = clean_rag.get("/api/memory/config").json()["config"]
    assert config["top_k"] == 9, "an earlier knob must survive a later patch"
    assert config["min_score"] == 0.4

    stored = rag_override.load_overrides(get_settings().app.data_dir)
    assert stored == {"top_k": 9, "min_score": 0.4}


def test_config_patch_rejects_an_empty_body(clean_rag: TestClient) -> None:
    response = clean_rag.put("/api/memory/config", json={})
    assert response.status_code == 400
    assert "No memory settings" in response.json()["detail"]


def test_config_patch_rejects_an_unknown_key(clean_rag: TestClient) -> None:
    assert clean_rag.put("/api/memory/config", json={"banana": 1}).status_code == 422


def test_config_patch_ignores_an_out_of_range_value(clean_rag: TestClient) -> None:
    """Invalid values are dropped by the overlay, never persisted (rag.json contract)."""
    response = clean_rag.put("/api/memory/config", json={"top_k": 0})
    assert response.status_code == 200
    assert response.json()["config"]["top_k"] == RAGConfig.model_fields["top_k"].default
    assert rag_override.load_overrides(get_settings().app.data_dir) == {}


def test_injection_toggles_are_writable(clean_rag: TestClient) -> None:
    response = clean_rag.put(
        "/api/memory/config", json={"inject_memory": False, "inject_repository": False}
    )
    assert response.status_code == 200
    config = response.json()["config"]
    assert config["inject_memory"] is False
    assert config["inject_repository"] is False


# ------------------------------------------------------------------- reset
def test_config_reset_restores_the_defaults(clean_rag: TestClient) -> None:
    clean_rag.put("/api/memory/config", json={"top_k": 9, "memory_max": 42})

    response = clean_rag.delete("/api/memory/config")

    assert response.status_code == 200
    # Defaults are env-aware: the suite runs with LUXION_RAG__PROVIDER=hash,
    # so compare against a freshly built Settings rather than bare RAGConfig().
    assert response.json()["config"] == Settings().rag.model_dump()
    assert rag_override.load_overrides(get_settings().app.data_dir) == {}


def test_config_reset_is_safe_on_an_empty_store(clean_rag: TestClient) -> None:
    assert clean_rag.delete("/api/memory/config").status_code == 200


# --------------------------------------------------------------- ordering
def test_config_routes_are_not_swallowed_by_the_id_route(clean_rag: TestClient) -> None:
    """``/config`` must not be parsed as ``{memory_id}`` (declared before it)."""
    assert clean_rag.get("/api/memory/config").status_code == 200
    # And the id route still works for a real integer.
    created = clean_rag.post("/api/memory", json={"text": "A note to delete"}).json()
    assert clean_rag.delete(f"/api/memory/{created['id']}").status_code == 204
    assert clean_rag.delete("/api/memory/not-a-number").status_code == 422


# --------------------------------------------------------------- model swap
def test_embedding_model_change_flags_a_reembed(clean_rag: TestClient) -> None:
    """Changing the model keeps the index (old vectors) but marks it stale."""
    clean_rag.post("/api/memory", json={"text": "Postgres is the production database"})

    next_model = EMBEDDING_MODELS[1].id
    response = clean_rag.put("/api/memory/config", json={"embedding_model": next_model})

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["embedding_model"] == next_model
    assert body["needs_reembed"] is True, "the index still holds the old vectors"
    assert body["chunks"] >= 1, "the memory chunk is kept, not destroyed"


def test_rag_json_survives_a_reload(clean_rag: TestClient) -> None:
    clean_rag.put("/api/memory/config", json={"chunk_chars": 1200})

    reset_settings_cache()
    assert get_settings().rag.chunk_chars == 1200

    path = rag_override.rag_path(get_settings().app.data_dir)
    assert json.loads(path.read_text(encoding="utf-8")) == {"chunk_chars": 1200}
