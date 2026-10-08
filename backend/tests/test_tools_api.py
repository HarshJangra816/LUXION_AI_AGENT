"""Tool HTTP surface: catalog, permissions, audit log, confirmations (PRD §18-21)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from luxion.config.settings import get_settings
from luxion.tools.confirmations import get_confirmations
from luxion.tools.permissions import PermissionEngine


def test_catalog_lists_the_initial_toolset(client: TestClient) -> None:
    body = client.get("/api/tools").json()
    assert body["enabled"] is True
    assert body["autonomy_level"] == get_settings().security.autonomy_level

    names = {tool["name"] for tool in body["tools"]}
    assert names == {
        "get_time",
        "get_date",
        "open_application",
        "close_application",
        "open_url",
        "take_screenshot",
        "system_stats",
        "read_file",
        "write_file",
        # Phase 5b — long-term memory
        "remember",
        "recall",
        "forget",
        # Phase 5c — repository intelligence
        "search_code",
    }
    remember = next(tool for tool in body["tools"] if tool["name"] == "remember")
    assert remember["risk"] == "medium"
    assert remember["category"] == "memory"
    assert remember["parameters"]["required"] == ["text"]
    recall_tool = next(tool for tool in body["tools"] if tool["name"] == "recall")
    assert recall_tool["risk"] == "low"
    write_file = next(tool for tool in body["tools"] if tool["name"] == "write_file")
    assert write_file["risk"] == "medium"
    assert write_file["permission"] == "allow"
    assert write_file["override"] is None
    assert write_file["parameters"]["required"] == ["path", "content"]
    assert (
        body["defaults"]
        and {"risk": "low", "level": body["defaults"][0]["level"]} == (body["defaults"][0])
    )


def test_exposed_endpoint_ranks_relevant_tools(client: TestClient) -> None:
    exposed = client.get("/api/tools/exposed", params={"q": "read my file"}).json()
    assert exposed[0] == "read_file"
    assert len(exposed) <= get_settings().tools.max_exposed


def test_permission_round_trip_and_clear(client: TestClient) -> None:
    updated = client.put("/api/tools/permissions/get_time", json={"level": "deny"}).json()
    assert updated["overrides"] == {"get_time": "deny"}

    report = client.get("/api/tools/permissions").json()
    assert report["overrides"]["get_time"] == "deny"

    catalog = client.get("/api/tools").json()
    entry = next(tool for tool in catalog["tools"] if tool["name"] == "get_time")
    assert entry["permission"] == "deny"
    assert entry["override"] == "deny"

    cleared = client.delete("/api/tools/permissions").json()
    assert cleared["overrides"] == {}
    assert client.get("/api/tools/permissions").json()["overrides"] == {}


def test_permission_validation(client: TestClient) -> None:
    assert client.put("/api/tools/permissions/get_time", json={"level": "maybe"}).status_code == 422
    assert (
        client.put("/api/tools/permissions/no_such_tool", json={"level": "deny"}).status_code == 404
    )
    # Category switches are always allowed.
    category = client.put("/api/tools/permissions/category:file", json={"level": "confirm"}).json()
    assert category["overrides"]["category:file"] == "confirm"
    client.delete("/api/tools/permissions")


def test_permission_changes_are_persisted_to_disk(client: TestClient) -> None:
    client.put("/api/tools/permissions/open_url", json={"level": "deny"})
    # A fresh engine reading the same file agrees.
    engine = PermissionEngine(get_settings())
    assert engine.overrides == {"open_url": "deny"}
    client.delete("/api/tools/permissions")
    assert PermissionEngine(get_settings()).overrides == {}


def test_audit_log_is_newest_first(client: TestClient) -> None:
    client.post("/api/tools/get_time/run", json={})
    body = client.get("/api/tools/log", params={"limit": 5}).json()
    assert body["entries"]
    assert body["entries"][0]["tool"] == "get_time"
    assert body["entries"][0]["result"] == "success"
    assert body["entries"][0]["duration_ms"] is not None


def test_manual_run_uses_the_same_permission_path(client: TestClient) -> None:
    ok = client.post("/api/tools/get_date/run", json={"args": {}}).json()
    assert ok["status"] == "ok"

    client.put("/api/tools/permissions/get_date", json={"level": "deny"})
    denied = client.post("/api/tools/get_date/run", json={"args": {}}).json()
    assert denied["status"] == "denied"
    assert "denied by policy" in denied["error"]
    client.delete("/api/tools/permissions")


def test_manual_run_honours_approved_flag_for_confirm_tools(client: TestClient) -> None:
    client.put("/api/tools/permissions/get_time", json={"level": "confirm"})

    pending = client.post("/api/tools/get_time/run", json={"args": {}}).json()
    assert pending["status"] == "denied"
    assert "declined" in pending["error"]

    approved = client.post("/api/tools/get_time/run", json={"args": {}, "approved": True}).json()
    assert approved["status"] == "ok"
    client.delete("/api/tools/permissions")


def test_manual_run_of_unknown_tool_returns_an_error(client: TestClient) -> None:
    body = client.post("/api/tools/nope/run", json={}).json()
    assert body["status"] == "error"
    assert "unknown tool" in body["error"]


def test_confirmation_endpoints_start_empty_and_404_on_stale_ids(
    client: TestClient,
) -> None:
    listed = client.get("/api/tools/confirmations").json()
    assert listed["confirmations"] == []
    assert listed["timeout_s"] > 0

    missing = client.post("/api/tools/confirmations/stale-id", json={"approved": True})
    assert missing.status_code == 404


def test_pending_confirmation_can_be_answered_once(client: TestClient) -> None:
    manager = get_confirmations()
    pending = manager.create(
        tool="write_file",
        risk="medium",
        args={"path": "x"},
        reason="user setting",
        description="write a file",
        conversation_id="c1",
    )
    listed = client.get("/api/tools/confirmations").json()["confirmations"]
    assert [item["id"] for item in listed] == [pending.id]
    assert listed[0]["args"] == {"path": "x"}

    first = client.post(f"/api/tools/confirmations/{pending.id}", json={"approved": True})
    assert first.json() == {"resolved": True}
    # A second answer must not win the race with the running turn.
    again = client.post(f"/api/tools/confirmations/{pending.id}", json={"approved": False})
    assert again.status_code == 404
    manager.forget(pending.id)
