"""Phase 3 unit tests: registry, schema, permissions, executor, audit, routing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from luxion.config.settings import Settings, get_settings
from luxion.tools.audit import log_path, read_log, redact
from luxion.tools.base import (
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolResult,
    ToolSpec,
    validate_args,
)
from luxion.tools.executor import ToolExecutor
from luxion.tools.permissions import AUTONOMY_MATRIX, PermissionEngine
from luxion.tools.registry import ToolRegistry, build_registry
from luxion.tools.router import select_tools

EXPECTED_BUILTIN_TOOLS = {
    "get_time",
    "get_date",
    "open_application",
    "close_application",
    "open_url",
    "take_screenshot",
    "system_stats",
    "read_file",
    "write_file",
    # Phase 5b — PRD §33.14 "Remember that…" / "What did I tell you…" / "Forget…"
    "remember",
    "recall",
    "forget",
    # Phase 5c — PRD §17 repository intelligence
    "search_code",
}


# ------------------------------------------------------------------- registry
def test_registry_ships_the_bundled_tools() -> None:
    registry = build_registry(get_settings())
    assert set(registry.names()) == EXPECTED_BUILTIN_TOOLS
    risks = {spec.name: spec.risk for spec in registry.specs()}
    # PRD §20 examples: get_time LOW, write_file MEDIUM; launch/kill are HIGH.
    assert risks["get_time"] == "low"
    assert risks["write_file"] == "medium"
    assert risks["open_application"] == "high"
    assert risks["close_application"] == "high"
    assert risks["take_screenshot"] == "low"
    # Memory: reading is free, writing/deleting persistent data is medium.
    assert risks["recall"] == "low"
    assert risks["remember"] == "medium"
    assert risks["forget"] == "medium"
    # Repository search only reads the index.
    assert risks["search_code"] == "low"


def test_every_tool_declares_a_json_schema() -> None:
    for spec in build_registry(get_settings()).specs():
        schema = spec.parameters
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties", {}), dict)
        assert set(schema.get("required", [])) <= set(schema["properties"])
        assert spec.description


def test_duplicate_registration_is_rejected() -> None:
    class Fake(Tool):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="get_time", description="dup")

        async def run(self, args, ctx) -> ToolResult:  # noqa: ANN001, ANN201
            return ToolResult()

    registry = ToolRegistry()
    registry.register(Fake())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Fake())


def test_openai_schema_shape() -> None:
    spec = build_registry(get_settings()).spec("read_file")
    assert spec is not None
    payload = spec.as_openai()
    assert payload["type"] == "function"
    assert payload["function"]["name"] == "read_file"
    assert payload["function"]["parameters"]["required"] == ["path"]


# -------------------------------------------------------------------- schema
def test_validate_args_rejects_missing_required() -> None:
    spec = build_registry(get_settings()).spec("read_file")
    assert spec is not None
    with pytest.raises(ToolArgumentError, match="missing required"):
        validate_args(spec, {})


def test_validate_args_rejects_unknown_and_wrong_types() -> None:
    spec = build_registry(get_settings()).spec("read_file")
    assert spec is not None
    with pytest.raises(ToolArgumentError, match="unknown argument"):
        validate_args(spec, {"path": "a", "nope": 1})
    with pytest.raises(ToolArgumentError, match="must be string"):
        validate_args(spec, {"path": 42})


def test_validate_args_accepts_optional_arguments() -> None:
    spec = build_registry(get_settings()).spec("read_file")
    assert spec is not None
    assert validate_args(spec, {"path": "a", "max_bytes": 10}) == {"path": "a", "max_bytes": 10}


# ---------------------------------------------------------------- permissions
def test_autonomy_matrix_covers_every_level_and_risk() -> None:
    assert set(AUTONOMY_MATRIX) == set(range(6))
    for level, row in AUTONOMY_MATRIX.items():
        assert set(row) == {"low", "medium", "high", "critical"}
        if level <= 1:  # PRD §22: answer-only / suggest-only never execute
            assert set(row.values()) == {"deny"}


def test_default_decision_at_autonomy_three(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 3})
    engine = PermissionEngine(settings)
    registry = build_registry(settings)
    levels = {spec.name: engine.decide(spec).level for spec in registry.specs()}
    assert levels["get_time"] == "allow"
    assert levels["write_file"] == "allow"
    assert levels["open_application"] == "confirm"
    assert levels["close_application"] == "confirm"


def test_high_risk_is_denied_at_autonomy_two(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 2})
    engine = PermissionEngine(settings)
    spec = build_registry(settings).spec("open_application")
    assert spec is not None
    assert engine.decide(spec).level == "deny"


def test_override_is_persisted_and_beats_the_default(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    engine = PermissionEngine(settings)
    spec = build_registry(settings).spec("get_time")
    assert spec is not None

    assert engine.decide(spec).source == "autonomy"
    engine.set_override("get_time", "deny")
    decision = engine.decide(spec)
    assert decision.level == "deny"
    assert decision.source == "override"
    assert json.loads(engine.path.read_text(encoding="utf-8")) == {"get_time": "deny"}

    engine.set_override("get_time", None)
    assert engine.decide(spec).level == "allow"
    assert not engine.path.exists()


def test_category_override_applies_to_the_whole_category(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    engine = PermissionEngine(settings)
    engine.set_override("category:application", "deny")
    registry = build_registry(settings)
    for name in ("open_application", "close_application"):
        spec = registry.spec(name)
        assert spec is not None
        assert engine.decide(spec).level == "deny"


def test_corrupt_permission_file_falls_back_to_defaults(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    settings.app.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.app.data_dir / "tool_permissions.json").write_text("{not json", encoding="utf-8")
    engine = PermissionEngine(settings)
    spec = build_registry(settings).spec("get_time")
    assert spec is not None
    assert engine.decide(spec).level == "allow"


# ------------------------------------------------------------------ executor
def _executor(settings: Settings) -> ToolExecutor:
    return ToolExecutor(build_registry(settings), PermissionEngine(settings), settings)


def test_executor_runs_a_read_only_tool(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 3})
    result = asyncio.run(_executor(settings).execute("get_time", {}))
    assert result.status == "ok"
    assert "Local:" in result.output
    assert result.duration_ms is not None


def test_executor_denies_when_autonomy_level_is_zero(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 0})
    result = asyncio.run(_executor(settings).execute("get_time", {}))
    assert result.status == "denied"
    assert result.ok is False


def test_executor_reports_unknown_tool(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    result = asyncio.run(_executor(settings).execute("does_not_exist", {}))
    assert result.status == "error"
    assert "unknown tool" in (result.error or "")


def test_executor_reports_invalid_arguments(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    result = asyncio.run(_executor(settings).execute("read_file", {}))
    assert result.status == "invalid_args"


def test_confirmation_runs_only_after_the_user_approves(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path})
    executor = _executor(settings)
    engine = executor.engine
    spec = build_registry(settings).spec("write_file")
    assert spec is not None
    engine.set_override("write_file", "confirm")

    prepared = executor.prepare(
        "write_file", {"path": "confirm.txt", "content": "hi"}, conversation_id="c1"
    )
    assert prepared.needs_confirmation
    assert prepared.pending is not None

    declined = asyncio.run(executor.run(prepared, approved=False))
    assert declined.status == "denied"
    assert not (tmp_path / "confirm.txt").exists()
    # The pending prompt is cleaned up either way.
    assert executor.confirmations.get(prepared.pending.id) is None
    engine.set_override("write_file", None)


def test_write_file_and_read_file_stay_inside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        app={"data_dir": tmp_path},
        security={"allowed_workspaces": [workspace]},
    )
    executor = _executor(settings)

    written = asyncio.run(executor.execute("write_file", {"path": "notes.txt", "content": "hello"}))
    assert written.status == "ok"
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"

    read = asyncio.run(executor.execute("read_file", {"path": "notes.txt"}))
    assert read.status == "ok"
    assert read.output == "hello"

    escaped = asyncio.run(executor.execute("read_file", {"path": str(tmp_path / "outside.txt")}))
    assert escaped.status == "error"
    assert "workspace" in (escaped.error or "").lower()


def test_tool_timeout_is_reported(tmp_path: Path) -> None:
    class Slow(Tool):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="slow_tool", description="sleeps", risk="low")

        async def run(self, args, ctx) -> ToolResult:  # noqa: ANN001, ANN201
            await asyncio.sleep(5)
            return ToolResult(output="never")

    settings = Settings(app={"data_dir": tmp_path}, tools={"timeout_s": 0.05})
    registry = build_registry(settings)
    registry.register(Slow())
    executor = ToolExecutor(registry, PermissionEngine(settings), settings)
    result = asyncio.run(executor.execute("slow_tool", {}))
    assert result.status == "timeout"


# --------------------------------------------------------------------- audit
def test_audit_log_records_success_and_denial(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, security={"autonomy_level": 3})
    executor = _executor(settings)
    asyncio.run(executor.execute("get_time", {}))
    asyncio.run(executor.execute("does_not_exist", {}))

    entries = read_log(settings, limit=10)
    assert [entry.tool for entry in entries] == ["does_not_exist", "get_time"]
    assert entries[0].result == "error"
    assert entries[1].result == "success"
    assert log_path(settings).exists()


def test_audit_log_redacts_credential_arguments() -> None:
    cleaned = redact({"api_key": "sk-secret", "path": "a.txt"})
    assert cleaned == {"api_key": "***", "path": "a.txt"}


def test_audit_log_stays_within_the_configured_limit(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, tools={"log_limit": 10})
    executor = _executor(settings)
    for _ in range(30):
        asyncio.run(executor.execute("get_time", {}))
    raw = log_path(settings).read_text(encoding="utf-8").splitlines()
    assert len(raw) <= 15


# -------------------------------------------------------------------- routing
def test_router_exposes_everything_under_the_cap() -> None:
    settings = get_settings()
    registry = build_registry(settings)
    selected = select_tools("open the weather", registry, settings)
    assert len(selected) == len(registry)


def test_router_respects_max_exposed(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, tools={"max_exposed": 3})
    registry = build_registry(settings)
    assert len(select_tools("anything at all", registry, settings)) == 3


def test_router_prefers_matching_tools() -> None:
    settings = Settings(app={"data_dir": get_settings().app.data_dir}, tools={"max_exposed": 2})
    registry = build_registry(settings)
    selected = select_tools("please read the contents of my file", registry, settings)
    assert selected[0].name == "read_file"


# --------------------------------------------------------------- dynamic load
def test_plugin_directory_registers_new_tools(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "echo_tool.py").write_text(
        "from luxion.tools.base import Tool, ToolResult, ToolSpec\n"
        "class Echo(Tool):\n"
        "    @property\n"
        "    def spec(self):\n"
        "        return ToolSpec(name='echo_text', description='Echo text back', risk='low',\n"
        "                        parameters={'type': 'object', 'properties': "
        "{'text': {'type': 'string'}}, 'required': ['text']})\n"
        "    async def run(self, args, ctx):\n"
        "        return ToolResult(output=str(args['text']))\n"
        "TOOLS = [Echo()]\n",
        encoding="utf-8",
    )
    settings = Settings(app={"data_dir": tmp_path}, tools={"plugin_dirs": [plugin_dir]})
    registry = build_registry(settings)
    assert "echo_text" in registry.names()

    result = asyncio.run(
        ToolExecutor(registry, PermissionEngine(settings), settings).execute(
            "echo_text", {"text": "hi"}
        )
    )
    assert result.status == "ok"
    assert result.output == "hi"


def test_broken_plugin_is_skipped_not_fatal(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "broken.py").write_text("raise RuntimeError('nope')\n", encoding="utf-8")
    settings = Settings(app={"data_dir": tmp_path}, tools={"plugin_dirs": [plugin_dir]})
    registry = build_registry(settings)
    assert set(registry.names()) == EXPECTED_BUILTIN_TOOLS


def test_tools_can_be_disabled_entirely(tmp_path: Path) -> None:
    settings = Settings(app={"data_dir": tmp_path}, tools={"enabled": False})
    assert len(build_registry(settings)) == 0


def test_context_reports_approved_workspaces(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(app={"data_dir": tmp_path}, security={"allowed_workspaces": [workspace]})
    ctx = ToolContext(settings)
    assert ctx.workspaces == [workspace]
