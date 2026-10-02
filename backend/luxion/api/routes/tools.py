"""Tool catalog, permissions, audit log and confirmations (PRD §18-21, §43)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from luxion.api.schemas import (
    ConfirmationList,
    ConfirmationOut,
    ConfirmationOutcome,
    ConfirmationResolve,
    PermissionReport,
    PermissionUpdate,
    ToolCatalog,
    ToolInfo,
    ToolLogResponse,
    ToolRunRequest,
)
from luxion.config.settings import get_settings
from luxion.security.capabilities import get_capabilities
from luxion.tools.audit import read_log
from luxion.tools.confirmations import get_confirmations
from luxion.tools.executor import ExecutionResult, get_executor
from luxion.tools.permissions import get_engine
from luxion.tools.registry import get_registry
from luxion.tools.router import select_tools

router = APIRouter(prefix="/tools", tags=["tools"])

_LEVELS: tuple[str, ...] = ("allow", "confirm", "deny")


def _catalog() -> ToolCatalog:
    settings = get_settings()
    registry = get_registry(settings)
    engine = get_engine(settings)
    overrides = engine.overrides
    infos: list[ToolInfo] = []
    for tool in registry.tools():
        spec = tool.spec
        decision = engine.decide(spec)
        permission, reason = decision.level, decision.reason
        if spec.requires:
            gate = get_capabilities(settings).check(spec.requires)
            if not gate.allowed:
                permission, reason = "deny", f"capability: {gate.reason}"
        infos.append(
            ToolInfo(
                name=spec.name,
                description=spec.description,
                risk=spec.risk,
                category=spec.category,
                tags=spec.tags,
                read_only=spec.read_only,
                parameters=spec.parameters,
                permission=permission,
                permission_reason=reason,
                override=overrides.get(spec.name),
                requires=spec.requires,
            )
        )
    return ToolCatalog(
        enabled=settings.tools.enabled,
        autonomy_level=settings.security.autonomy_level,
        tools=infos,
        defaults=engine.defaults(),
    )


@router.get("", response_model=ToolCatalog)
def list_tools() -> ToolCatalog:
    """Every registered tool with its effective permission (PRD §18)."""
    return _catalog()


@router.get("/exposed", response_model=list[str])
def exposed_tools(q: str = "") -> list[str]:
    """What the model would be offered for a trial query (PRD §19)."""
    settings = get_settings()
    registry = get_registry(settings)
    return [spec.name for spec in select_tools(q, registry, settings)]


@router.get("/permissions", response_model=PermissionReport)
def get_permissions() -> PermissionReport:
    settings = get_settings()
    engine = get_engine(settings)
    return PermissionReport(overrides=engine.overrides, defaults=engine.defaults())


@router.put("/permissions/{name}", response_model=PermissionReport)
def set_permission(name: str, body: PermissionUpdate) -> PermissionReport:
    """Set or (with ``level: null``) clear one override — any tool name, or
    ``category:<name>`` to switch a whole category at once."""
    if body.level is not None and body.level not in _LEVELS:
        raise HTTPException(
            status_code=422, detail=f"level must be one of {', '.join(_LEVELS)} or null"
        )
    engine = get_engine(get_settings())
    known = set(get_registry(get_settings()).names())
    if name not in known and not name.startswith("category:"):
        raise HTTPException(status_code=404, detail=f"Unknown tool '{name}'")
    engine.set_override(name, body.level)  # type: ignore[arg-type]
    return PermissionReport(overrides=engine.overrides, defaults=engine.defaults())


@router.delete("/permissions", response_model=PermissionReport)
def clear_permissions() -> PermissionReport:
    engine = get_engine(get_settings())
    engine.clear()
    return PermissionReport(overrides={}, defaults=engine.defaults())


@router.get("/log", response_model=ToolLogResponse)
def tool_log(limit: int = 50) -> ToolLogResponse:
    """Newest-first audit log (PRD §43)."""
    settings = get_settings()
    limit = max(1, min(limit, settings.tools.log_limit))
    entries: list[Any] = [entry.model_dump() for entry in read_log(settings, limit=limit)]
    return ToolLogResponse(entries=entries)


@router.get("/confirmations", response_model=ConfirmationList)
def pending_confirmations() -> ConfirmationList:
    manager = get_confirmations(get_settings().tools.confirm_timeout_s)
    return ConfirmationList(
        confirmations=[ConfirmationOut(**item) for item in manager.pending()],
        timeout_s=manager.timeout_s,
    )


@router.post("/confirmations/{confirmation_id}", response_model=ConfirmationOutcome)
def resolve_confirmation(confirmation_id: str, body: ConfirmationResolve) -> ConfirmationOutcome:
    """Answer a prompt raised mid-turn (PRD §21). Unknown ids are 404 so the
    UI can tell a stale prompt from a live one."""
    manager = get_confirmations(get_settings().tools.confirm_timeout_s)
    if not manager.resolve(confirmation_id, body.approved):
        raise HTTPException(status_code=404, detail="Confirmation not found or already answered")
    return ConfirmationOutcome(resolved=True)


@router.post("/{name}/run", response_model=ExecutionResult)
async def run_tool(name: str, body: ToolRunRequest) -> ExecutionResult:
    """Run a tool once from Settings (same permission path as the agent)."""
    settings = get_settings()
    executor = get_executor(settings)
    prepared = executor.prepare(name, body.args)
    approved: bool | None = None
    if prepared.needs_confirmation:
        approved = body.approved
    return await executor.run(prepared, approved=approved)
