"""Usage totals, cost and the per-conversation context report (PRD §14)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _events(response) -> list[tuple[str, dict]]:  # noqa: ANN001 - httpx.Response
    events: list[tuple[str, dict]] = []
    name = ""
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            events.append((name, json.loads(line[len("data: ") :])))
    return events


def _turn(client: TestClient, conversation_id: str, content: str) -> list[tuple[str, dict]]:
    with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        json={"content": content},
    ) as response:
        assert response.status_code == 200
        return _events(response)


def _done(events: list[tuple[str, dict]]) -> dict:
    return next(payload for name, payload in events if name == "done")


def test_usage_report_tracks_turns_budget_and_context(client: TestClient) -> None:
    before = client.get("/api/usage").json()
    conversation_id = client.post("/api/conversations", json={"title": "usage"}).json()["id"]
    done = _done(_turn(client, conversation_id, "measure me"))
    after = client.get("/api/usage").json()

    assert after["totals"]["messages"] == before["totals"]["messages"] + 2
    assert after["totals"]["conversations"] == before["totals"]["conversations"] + 1
    assert (
        after["totals"]["tokens_out"]
        == before["totals"]["tokens_out"] + done["usage"]["completion_tokens"]
    )
    assert after["totals"]["tokens_in"] > 0
    # Only providers that report spend (OpenRouter) move this number.
    assert after["totals"]["cost_usd"] >= 0

    budget = after["budget"]
    assert budget["total"] == 32_000
    assert budget["keep_recent_messages"] == 6
    assert budget["summary_enabled"] is True
    assert budget["spendable"] == budget["total"] - budget["reserve"] - budget["response"]

    entry = next(item for item in after["conversations"] if item["id"] == conversation_id)
    assert entry["messages"] == 2
    assert entry["tokens_out"] == done["usage"]["completion_tokens"]

    recent = after["recent_turns"][0]
    assert recent["conversation_id"] == conversation_id
    assert recent["context"] is not None
    assert recent["context"]["budget_tokens"] == 32_000

    # The same composition is served again from the persisted message.
    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assistant = detail["messages"][1]
    assert assistant["context"]["estimated_tokens"] == recent["context"]["estimated_tokens"]
    assert done["context"]["estimated_tokens"] == assistant["context"]["estimated_tokens"]


def test_conversation_context_report_describes_the_next_turn(client: TestClient) -> None:
    conversation_id = client.post("/api/conversations", json={"title": None}).json()["id"]
    _turn(client, conversation_id, "first turn")
    _turn(client, conversation_id, "second turn")

    report = client.get(f"/api/usage/{conversation_id}").json()
    assert report["conversation_id"] == conversation_id
    assert report["title"] == "first turn"
    assert report["totals"]["messages"] == 4
    assert report["totals"]["tokens_out"] > 0

    context = report["context"]
    assert context["history_available"] == 4
    assert context["history_sent"] == 4
    assert context["history_dropped"] == 0
    assert context["messages_sent"] == 5  # system prompt + four turns
    assert context["system_tokens"] > 0
    assert context["compression"] == "none"
    assert context["truncated"] is False
    assert context["estimated_tokens"] == (
        context["system_tokens"] + context["summary_tokens"] + context["history_tokens"]
    )

    assert report["summary"]["present"] is False
    assert report["budget"]["total"] == 32_000


def test_conversation_context_report_is_read_only(client: TestClient) -> None:
    """The preview must not create a summary as a side effect."""
    conversation_id = client.post("/api/conversations", json={"title": "preview"}).json()["id"]
    _turn(client, conversation_id, "one")

    first = client.get(f"/api/usage/{conversation_id}").json()
    second = client.get(f"/api/usage/{conversation_id}").json()
    assert first["summary"] == second["summary"]
    assert first["context"] == second["context"]


def test_unknown_conversation_context_returns_404(client: TestClient) -> None:
    assert client.get("/api/usage/does-not-exist").status_code == 404
