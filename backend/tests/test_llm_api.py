"""LLM status endpoints used by Settings."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_llm_status_reports_active_provider(client: TestClient) -> None:
    response = client.get("/api/llm/status")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["label"] == "Mock (offline)"
    assert body["api_key_configured"] is False
    # The raw key must never appear in an API response.
    assert "api_key" not in body
    assert {spec["id"] for spec in body["available_providers"]} >= {"ollama", "openai", "mock"}


def test_llm_health_probes_the_provider(client: TestClient) -> None:
    response = client.get("/api/llm/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "mock"
    assert body["models"] == ["mock-1"]
    assert body["error"] is None
