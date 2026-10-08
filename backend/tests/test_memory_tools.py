"""Phase 5b tool tests: ``remember`` / ``recall`` / ``forget`` (PRD §33.14)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luxion.config.settings import Settings, get_settings
from luxion.database.session import get_session_factory, init_db
from luxion.memory import store
from luxion.tools.base import Tool, ToolArgumentError, ToolContext, ToolError
from luxion.tools.executor import ToolExecutor
from luxion.tools.permissions import PermissionEngine
from luxion.tools.registry import build_registry
from luxion.tools.router import select_tools


@pytest.fixture()
def session():  # noqa: ANN201
    init_db()
    db = get_session_factory()()
    store.clear_memories(db)
    try:
        yield db
    finally:
        store.clear_memories(db)
        db.close()


def _tool(name: str) -> Tool:
    tool = build_registry(get_settings()).get(name)
    assert tool is not None, f"{name} must be registered"
    return tool


def _run(tool: Tool, **args):  # noqa: ANN001, ANN201
    context = ToolContext(get_settings(), conversation_id=None)
    return asyncio.run(tool.run(args, context))


# ---------------------------------------------------------------- remember
def test_remember_tool_stores_a_statement(session) -> None:
    result = _run(_tool("remember"), text="Prefers the window on the left", kind="preference")

    assert result.ok is True
    assert result.output.startswith("Saved memory #")
    assert result.data["created"] is True
    assert result.data["kind"] == "preference"
    assert [memory.text for memory in store.list_memories(session)] == [
        "Prefers the window on the left"
    ]


def test_remember_tool_reports_an_already_known_statement(session) -> None:
    _run(_tool("remember"), text="Prefers the window on the left")
    result = _run(_tool("remember"), text="prefers the window on the LEFT")

    assert result.data["created"] is False
    assert result.output.startswith("Already stored as #")
    assert store.count_memories(session) == 1


def test_remember_tool_rejects_a_blank_statement(session) -> None:
    with pytest.raises(ToolArgumentError, match="'text' must be a non-empty string"):
        _run(_tool("remember"), text="   ")
    assert store.count_memories(session) == 0


def test_remember_tool_surfaces_a_rejected_kind(session) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run(_tool("remember"), text="A durable statement", kind="banana")
    assert excinfo.value.code == "memory_rejected"
    assert store.count_memories(session) == 0


def test_remember_tool_validates_and_clamps_importance(session) -> None:
    with pytest.raises(ToolArgumentError, match="'importance' must be a number"):
        _run(_tool("remember"), text="A durable statement", importance="lots")

    result = _run(_tool("remember"), text="A pinned statement", importance=9)
    assert result.data["importance"] == 1.0
    assert store.count_memories(session) == 1


def test_remember_tool_defaults_the_kind(session) -> None:
    result = _run(_tool("remember"), text="An ordinary fact")
    assert result.data["kind"] == "fact"


# ------------------------------------------------------------------ recall
def test_recall_tool_returns_hits_and_a_prompt_preview(session) -> None:
    _run(_tool("remember"), text="Postgres is the production database", kind="fact")

    result = _run(_tool("recall"), query="production database")

    assert result.ok is True
    assert result.data["query"] == "production database"
    assert len(result.data["hits"]) == 1
    assert result.data["preview"] == "- [fact] Postgres is the production database"
    assert "[fact]" in result.output
    assert "importance" in result.output


def test_recall_tool_clamps_k(session) -> None:
    _run(_tool("remember"), text="Postgres is the production database")

    assert len(_run(_tool("recall"), query="database", k=999).data["hits"]) <= 20
    assert _run(_tool("recall"), query="database", k=0).data["hits"]


def test_recall_tool_says_when_nothing_matches(session, monkeypatch) -> None:
    import importlib

    recall_mod = importlib.import_module("luxion.memory.recall")
    monkeypatch.setattr(recall_mod, "_embed_query", lambda _query: None)
    result = _run(_tool("recall"), query="flibbertigibbet")

    assert result.data["hits"] == []
    assert result.output == "No memories match 'flibbertigibbet'."


def test_recall_tool_rejects_a_blank_query(session) -> None:
    with pytest.raises(ToolArgumentError, match="'query' must be a non-empty string"):
        _run(_tool("recall"), query=" ")


# ------------------------------------------------------------------ forget
def test_forget_tool_deletes_by_id(session) -> None:
    created = _run(_tool("remember"), text="Delete me shortly")
    memory_id = int(created.data["id"])

    result = _run(_tool("forget"), memory_id=memory_id)

    assert result.data == {"id": memory_id, "text": "Delete me shortly", "deleted": True}
    assert store.count_memories(session) == 0


def test_forget_tool_deletes_by_query(session) -> None:
    created = _run(_tool("remember"), text="The obsolete setting is turned off")
    memory_id = int(created.data["id"])

    result = _run(_tool("forget"), query="obsolete setting")

    assert result.data["id"] == memory_id
    assert result.data["deleted"] is True
    assert store.count_memories(session) == 0


def test_forget_tool_requires_an_id_or_a_query(session) -> None:
    with pytest.raises(ToolArgumentError, match="pass 'memory_id' or 'query'"):
        _run(_tool("forget"))


def test_forget_tool_rejects_an_unknown_id(session) -> None:
    with pytest.raises(ToolError) as excinfo:
        _run(_tool("forget"), memory_id=4_242_424)
    assert excinfo.value.code == "memory_not_found"


def test_forget_tool_reports_an_unmatched_query(session, monkeypatch) -> None:
    import importlib

    recall_mod = importlib.import_module("luxion.memory.recall")
    monkeypatch.setattr(recall_mod, "_embed_query", lambda _query: None)
    _run(_tool("remember"), text="Something entirely different")
    with pytest.raises(ToolError) as excinfo:
        _run(_tool("forget"), query="flibbertigibbet")
    assert excinfo.value.code == "memory_not_found"
    assert store.count_memories(session) == 1


# ------------------------------------------------------------------ routing
def test_router_surfaces_the_memory_tools_for_a_memory_question() -> None:
    settings = Settings(app={"data_dir": get_settings().app.data_dir}, tools={"max_exposed": 3})
    registry = build_registry(settings)

    asking = [spec.name for spec in select_tools("what did I tell you about", registry, settings)]
    storing = [spec.name for spec in select_tools("remember that I prefer vim", registry, settings)]

    assert "recall" in asking
    assert "remember" in storing
    assert select_tools("remember that I prefer vim", registry, settings)[0].name == "remember"


def test_memory_tool_specs_match_the_risk_model() -> None:
    registry = build_registry(get_settings())
    assert registry.spec("recall").read_only is True
    assert registry.spec("remember").risk == "medium"
    assert registry.spec("forget").risk == "medium"
    assert registry.spec("recall").category == "memory"


# ------------------------------------------------------- permission gating
def test_remember_is_denied_at_autonomy_zero(tmp_path: Path, session) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 0})
    executor = ToolExecutor(build_registry(settings), PermissionEngine(settings), settings)

    result = asyncio.run(executor.execute("remember", {"text": "Should never be stored"}))

    assert result.status == "denied"
    assert store.count_memories(session) == 0


def test_remember_needs_confirmation_while_recall_allows_at_level_two(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 2})
    registry = build_registry(settings)
    engine = PermissionEngine(settings)

    assert engine.decide(registry.spec("remember")).level == "confirm"
    assert engine.decide(registry.spec("forget")).level == "confirm"
    assert engine.decide(registry.spec("recall")).level == "allow"
