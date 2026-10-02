"""Streaming chat endpoint: deltas, persistence, error mapping."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _events(response) -> list[tuple[str, dict]]:  # noqa: ANN001 - httpx.Response
    """Parse an SSE body into ``(event_name, payload)`` tuples."""
    events: list[tuple[str, dict]] = []
    name = ""
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            events.append((name, json.loads(line[len("data: ") :])))
    return events


def _new_conversation(client: TestClient, title: str | None = "chat") -> str:
    return client.post("/api/conversations", json={"title": title}).json()["id"]


def test_stream_deltas_then_done(client: TestClient) -> None:
    conversation_id = _new_conversation(client)

    with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "hello Luxion"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)

    deltas = [payload for name, payload in events if name == "delta"]
    assert len(deltas) > 1
    assert events[-1][0] == "done"

    text = "".join(payload["text"] for payload in deltas)
    assert "hello Luxion" in text

    done = events[-1][1]
    assert done["conversation_id"] == conversation_id
    assert done["message_id"] is not None
    assert done["usage"]["total_tokens"] > 0


def test_stream_persists_both_turns_and_titles_conversation(client: TestClient) -> None:
    conversation_id = _new_conversation(client, title=None)

    with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Summarise my day"},
    ) as response:
        events = _events(response)

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["tokens_out"] is not None
    # Untitled conversations are named after their first user turn.
    assert detail["title"] == "Summarise my day"
    assert events[-1][0] == "done"


def test_second_turn_includes_history(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    for content in ("first", "second"):
        with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": content},
        ) as response:
            _events(response)

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert [message["role"] for message in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_provider_failure_becomes_error_event(client: TestClient) -> None:
    conversation_id = _new_conversation(client)

    with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "FAIL now"},
    ) as response:
        events = _events(response)

    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "provider_response"
    assert events[-1][1]["retryable"] is False

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    # The user turn survives so the user can retry.
    assert [message["role"] for message in detail["messages"]] == ["user"]


def test_missing_conversation_returns_404(client: TestClient) -> None:
    response = client.post("/api/conversations/does-not-exist/messages", json={"content": "hi"})
    assert response.status_code == 404


def test_blank_message_is_rejected(client: TestClient) -> None:
    conversation_id = _new_conversation(client)
    response = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": "   "}
    )
    assert response.status_code == 422


def test_conversation_list_orders_by_recent_activity(client: TestClient) -> None:
    first = _new_conversation(client, "older")
    second = _new_conversation(client, "newer")
    with client.stream(
        "POST",
        f"/api/conversations/{first}/messages",
        json={"content": "bump me"},
    ) as response:
        _events(response)

    ids = [item["id"] for item in client.get("/api/conversations").json()]
    assert ids.index(first) < ids.index(second)
