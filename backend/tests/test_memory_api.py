"""Memory API tests: list / create / search / delete (PRD §33.14, Settings → Memory)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from luxion.database.session import get_session_factory, init_db
from luxion.memory import store


@pytest.fixture(autouse=True)
def clean():  # noqa: ANN201
    init_db()
    _clear()
    yield
    _clear()


def _clear() -> None:
    with get_session_factory()() as session:
        store.clear_memories(session)


def test_list_starts_empty_and_reports_totals(client: TestClient) -> None:
    payload = client.get("/api/memory").json()
    assert payload == {"items": [], "total": 0, "kind": None}


def test_create_then_list_then_filter_by_kind(client: TestClient) -> None:
    created = client.post(
        "/api/memory",
        json={"text": "Prefers the window on the left", "kind": "preference", "importance": 0.8},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "preference"
    assert body["importance"] == 0.8
    assert body["source"] == "user"
    assert body["score"] is None
    memory_id = body["id"]

    listed = client.get("/api/memory").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == memory_id

    only_facts = client.get("/api/memory", params={"kind": "fact"}).json()
    assert only_facts == {"items": [], "total": 0, "kind": "fact"}

    only_preferences = client.get("/api/memory", params={"kind": "preference"}).json()
    assert only_preferences["total"] == 1


def test_list_rejects_an_unknown_kind(client: TestClient) -> None:
    response = client.get("/api/memory", params={"kind": "secret"})
    assert response.status_code == 400
    assert "Unknown kind" in response.json()["detail"]


def test_create_dedupes_and_clamps_the_payload(client: TestClient) -> None:
    first = client.post("/api/memory", json={"text": "Prefers Postgres"})
    second = client.post("/api/memory", json={"text": "prefers  postgres."})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get("/api/memory").json()["total"] == 1

    # The schema clamps the input before the store ever sees it (0..1, ge/le).
    pinned = client.post("/api/memory", json={"text": "A pinned note", "importance": 1.0}).json()
    assert pinned["importance"] == 1.0
    assert (
        client.post("/api/memory", json={"text": "Too important", "importance": 1.5}).status_code
        == 422
    )


def test_create_reports_bad_input(client: TestClient) -> None:
    assert client.post("/api/memory", json={"text": "   "}).status_code == 400
    assert (
        client.post("/api/memory", json={"text": "A statement", "kind": "banana"}).status_code
        == 400
    )
    assert (
        client.post("/api/memory", json={"text": "A statement", "importance": 5}).status_code == 422
    )
    assert client.post("/api/memory", json={"kind": "fact"}).status_code == 422


def test_search_returns_ranked_hits_and_a_prompt_preview(client: TestClient) -> None:
    client.post("/api/memory", json={"text": "Postgres is the production database"})

    payload = client.post("/api/memory/search", json={"query": "production database"}).json()

    assert payload["query"] == "production database"
    assert len(payload["hits"]) == 1
    assert payload["hits"][0]["score"] > 0
    assert payload["preview"] == "- [fact] Postgres is the production database"


def test_search_can_filter_by_kind(client: TestClient) -> None:
    client.post("/api/memory", json={"text": "Zebra preference: likes tabs", "kind": "preference"})
    client.post("/api/memory", json={"text": "Zebra fact: uses vim", "kind": "fact"})

    everything = client.post("/api/memory/search", json={"query": "zebra"}).json()
    assert len(everything["hits"]) == 2

    filtered = client.post(
        "/api/memory/search", json={"query": "zebra", "kinds": ["preference"]}
    ).json()
    assert [hit["kind"] for hit in filtered["hits"]] == ["preference"]
    assert filtered["preview"].startswith("- [preference] ")


def test_search_rejects_a_bad_kind(client: TestClient) -> None:
    response = client.post("/api/memory/search", json={"query": "zebra", "kinds": ["banana"]})
    assert response.status_code == 400
    assert "Unknown kind" in response.json()["detail"]
    assert client.post("/api/memory/search", json={"query": ""}).status_code == 422


def test_delete_one_and_delete_all(client: TestClient) -> None:
    first = client.post("/api/memory", json={"text": "First disposable note"}).json()
    client.post("/api/memory", json={"text": "Second disposable note"})

    assert client.delete(f"/api/memory/{first['id']}").status_code == 204
    assert client.get("/api/memory").json()["total"] == 1

    assert client.delete("/api/memory/987654").status_code == 404

    assert client.delete("/api/memory").json() == {"deleted": 1}
    assert client.get("/api/memory").json()["total"] == 0
    assert client.delete("/api/memory").json() == {"deleted": 0}
