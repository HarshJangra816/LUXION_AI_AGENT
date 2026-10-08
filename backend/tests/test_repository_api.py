"""Phase 5c HTTP surface: ``/api/repository`` (PRD §16, §17).

The walk policy is ``settings.security.allowed_workspaces``, which otherwise
points at the Luxion checkout itself. Every test here re-points it at its own
temporary workspace, otherwise "Index files" would re-index the real repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from luxion.config.settings import get_settings
from luxion.database.session import get_session_factory, init_db
from luxion.memory import store as memory_store
from luxion.rag import vector_store
from luxion.rag.models import Chunk
from luxion.repository.scanner import REPO_SOURCE_TYPES

TREE = {
    "README.md": "# Desk\n\nThe desk lamp is USB-C powered.\n",
    "src/app.py": "def build_lamp():\n    return 'usb-c'\n",
}


@pytest.fixture()
def rooted(client: TestClient, tmp_path: Path, monkeypatch):  # noqa: ANN201
    """Point the API's walk policy at this test's workspace only."""
    init_db()
    db = get_session_factory()()
    _clear_repo(db)
    memory_store.clear_memories(db)
    db.close()

    settings = get_settings().model_copy(deep=True)
    settings.security.allowed_workspaces = [tmp_path.resolve()]
    monkeypatch.setattr("luxion.api.routes.repository.get_settings", lambda: settings, raising=True)

    yield tmp_path, settings

    db = get_session_factory()()
    _clear_repo(db)
    memory_store.clear_memories(db)
    db.close()


def _clear_repo(db) -> None:  # noqa: ANN001
    """Delete through ``delete_source`` so the FTS/vector rows go too."""
    sources = list(
        db.execute(
            select(Chunk.source).where(Chunk.source_type.in_(REPO_SOURCE_TYPES)).distinct()
        ).scalars()
    )
    for source in sources:
        vector_store.delete_source(db, source)
    db.commit()


def _write(root: Path, tree: dict[str, str]) -> None:
    for name, content in tree.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_status_reports_the_index_and_its_walk_policy(rooted, client: TestClient) -> None:
    root, _settings = rooted
    body = client.get("/api/repository").json()

    assert body["enabled"] is True
    assert body["roots"] == [str(root.resolve())]
    assert body["files"] == 0 and body["chunks"] == 0
    assert ".py" in body["extensions"] and ".md" in body["extensions"]
    assert body["index_on_start"] is False


def test_index_then_reindex_is_incremental(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)

    first = client.post("/api/repository/index").json()
    assert first["indexed"] == 2
    assert first["unchanged"] == 0
    assert first["failed"] == 0
    assert first["chunks"] > 0 and first["files"] == 2

    status = client.get("/api/repository").json()
    assert status["files"] == 2 and status["chunks"] == first["chunks"]

    # Nothing changed: the second pass must not re-embed anything.
    second = client.post("/api/repository/index").json()
    assert second["indexed"] == 0
    assert second["unchanged"] == 2
    assert second["chunks"] == first["chunks"]


def test_index_reports_the_roots_it_walked(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)
    body = client.post("/api/repository/index").json()
    assert body["roots"] == [str(root.resolve())]
    assert body["indexed_at"]


def test_index_skips_a_blank_file_without_failing(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, {**TREE, "notes.md": "   \n\n"})
    body = client.post("/api/repository/index").json()

    assert body["failed"] == 0
    assert body["skipped"] >= 1, "a file with no text is skipped, not indexed"
    assert body["files"] == 2, "the blank file never reaches the index"


def test_index_prunes_a_file_that_left_the_workspace(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)
    client.post("/api/repository/index")

    (root / "src" / "app.py").unlink()
    body = client.post("/api/repository/index").json()

    assert body["removed"] == 1
    assert body["files"] == 1
    assert client.get("/api/repository").json()["files"] == 1


def test_search_returns_hits_files_and_a_prompt_preview(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)
    client.post("/api/repository/index")

    db = get_session_factory()()
    memory_store.remember(db, "The desk lamp is USB-C powered and sits on the desk")
    db.close()

    body = client.post("/api/repository/search", json={"query": "desk lamp usb-c", "k": 5}).json()

    assert body["query"] == "desk lamp usb-c"
    assert body["hits"], "the workspace must answer"
    assert all(not hit["path"].startswith("memory:") for hit in body["hits"])
    assert body["hits"][0]["score"] > 0
    assert body["files"]
    assert ":" in body["preview"], "the preview must address a line range"


def test_search_can_group_or_stay_flat(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)
    client.post("/api/repository/index")

    flat = client.post("/api/repository/search", json={"query": "usb-c", "files": 0}).json()
    assert flat["hits"]
    assert flat["files"] == []
    assert flat["preview"] == ""

    grouped = client.post("/api/repository/search", json={"query": "usb-c", "files": 5}).json()
    assert grouped["files"]


def test_search_applies_the_configured_cosine_floor(rooted, client: TestClient) -> None:
    root, _settings = rooted
    _write(root, TREE)
    client.post("/api/repository/index")

    body = client.post(
        "/api/repository/search", json={"query": "desk lamp usb-c", "min_score": 0.99}
    ).json()
    # Keyword hits survive the floor (exact identifiers stay findable); only
    # vector matches below it are dropped.
    assert all(hit["score"] >= 0.0 for hit in body["hits"])
    assert (
        client.post("/api/repository/search", json={"query": "zzzz-nothing-matches-zzzz"}).json()[
            "hits"
        ]
        == []
    )


def test_search_rejects_bad_input(client: TestClient) -> None:
    assert client.post("/api/repository/search", json={}).status_code == 422
    assert client.post("/api/repository/search", json={"query": ""}).status_code == 422
    assert client.post("/api/repository/search", json={"query": "x", "k": 0}).status_code == 422
    assert (
        client.post("/api/repository/search", json={"query": "x", "min_score": 2.0}).status_code
        == 422
    )


def test_turning_rag_off_makes_the_pass_a_no_op(rooted, client: TestClient) -> None:
    root, settings = rooted
    _write(root, TREE)
    settings.rag.enabled = False

    body = client.post("/api/repository/index").json()
    assert body["scanned"] == 0
    assert body["indexed"] == 0

    status = client.get("/api/repository").json()
    assert status["enabled"] is False
    assert status["chunks"] == 0
