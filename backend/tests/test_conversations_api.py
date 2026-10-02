"""Conversation CRUD endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_list_conversations(client: TestClient) -> None:
    created = client.post("/api/conversations", json={"title": "First chat"})
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "First chat"
    assert body["message_count"] == 0

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json())


def test_create_without_body_uses_null_title(client: TestClient) -> None:
    response = client.post("/api/conversations")
    assert response.status_code == 201
    assert response.json()["title"] is None


def test_get_conversation_includes_messages(client: TestClient) -> None:
    created = client.post("/api/conversations", json={"title": "detail"}).json()

    fetched = client.get(f"/api/conversations/{created['id']}")
    assert fetched.status_code == 200
    detail = fetched.json()
    assert detail["id"] == created["id"]
    assert detail["messages"] == []


def test_unknown_conversation_is_404(client: TestClient) -> None:
    assert client.get("/api/conversations/nope").status_code == 404
    assert client.delete("/api/conversations/nope").status_code == 404


def test_delete_conversation_removes_it(client: TestClient) -> None:
    created = client.post("/api/conversations", json={"title": "doomed"}).json()

    assert client.delete(f"/api/conversations/{created['id']}").status_code == 204
    assert client.get(f"/api/conversations/{created['id']}").status_code == 404
    assert all(item["id"] != created["id"] for item in client.get("/api/conversations").json())
