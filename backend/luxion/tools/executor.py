"""Tool executor (PRD §3.1): permission check → run → log → result.

Split into :meth:`ToolExecutor.prepare` and :meth:`ToolExecutor.run` so the
agent loop can *yield* the confirmation prompt to the UI and await the user's
answer between the two stages. :meth:`ToolExecutor.execute` is the one-shot
form used when no one is watching the stream.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from luxion.config.settings import Settings
from luxion.security.capabilities import CapabilityStore, get_capabilities
from luxion.tools.audit import append_log, build_entry
from luxion.tools.base import (
    PermissionLevel,
    ToolArgumentError,
    ToolContext,
    ToolError,
    ToolSpec,
    validate_args,
)
from luxion.tools.confirmations import ConfirmationManager, PendingConfirmation, get_confirmations
from luxion.tools.permissions import PermissionDecision, PermissionEngine
from luxion.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

ExecutionStatus = Literal["ok", "error", "denied", "timeout", "invalid_args"]


@dataclass(slots=True)
class PreparedTool:
    """A validated, permission-checked request that is ready to run."""

    name: str
    spec: ToolSpec | None
    args: dict[str, Any]
    decision: PermissionDecision
    #: Set when the request died before execution (unknown tool / bad args).
    status: ExecutionStatus | None = None
    error: str | None = None
    pending: PendingConfirmation | None = None
    conversation_id: str | None = None

    @property
    def needs_confirmation(self) -> bool:
        return self.pending is not None


class ExecutionResult(BaseModel):
    """Uniform outcome — drives the UI chip, the audit log and the model reply."""

    tool: str
    status: ExecutionStatus
    output: str = ""
    error: str | None = None
    duration_ms: float | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    risk: str = "low"
    permission: PermissionLevel | Literal["n/a"] = "n/a"
    permission_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def label(self) -> str:
        return {
            "ok": "ok",
            "error": "failed",
            "denied": "denied",
            "timeout": "timed out",
            "invalid_args": "invalid arguments",
        }[self.status]

    def as_model_payload(self, max_chars: int) -> str:
        """What the LLM reads back. Failures must be obvious, not silent."""
        if self.status == "ok":
            text = self.output or "(no output)"
        else:
            text = f"error: {self.error or self.status}"
        prefix = f"[{self.tool}] {self.label}\n"
        room = max(200, max_chars - len(prefix))
        return prefix + (text if len(text) <= room else f"{text[:room]}…[truncated]")

    def summary(self) -> dict[str, Any]:
        """Compact record stored on the assistant message (``meta['tools']``)."""
        return {
            "name": self.tool,
            "status": self.status,
            "risk": self.risk,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "args": self.args,
            "output": self.output[:500],
        }


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        engine: PermissionEngine,
        settings: Settings,
        confirmations: ConfirmationManager | None = None,
        capabilities: CapabilityStore | None = None,
    ) -> None:
        self.registry = registry
        self.engine = engine
        self.settings = settings
        self.confirmations = confirmations or get_confirmations()
        self.capabilities = capabilities or get_capabilities(settings)

    # ---------------------------------------------------------------- prepare
    def prepare(
        self, name: str, args: dict[str, Any] | None, *, conversation_id: str | None = None
    ) -> PreparedTool:
        tool = self.registry.get(name)
        if tool is None:
            return PreparedTool(
                name=name,
                spec=None,
                args=dict(args or {}),
                decision=PermissionDecision(
                    tool=name, level="deny", source="autonomy", reason="tool is not registered"
                ),
                status="error",
                error=f"unknown tool '{name}'",
                conversation_id=conversation_id,
            )

        spec = tool.spec
        if spec.requires is not None:
            gate = self.capabilities.check(spec.requires)
            if not gate.allowed:
                # Hard block: runs before the permission engine, so no
                # autonomy level can override it (PRD §39).
                return PreparedTool(
                    name=name,
                    spec=spec,
                    args=dict(args or {}),
                    decision=PermissionDecision(
                        tool=name, level="deny", source="capability", reason=gate.reason
                    ),
                    status="denied",
                    error=f"capability '{spec.requires}' denied: {gate.reason}",
                    conversation_id=conversation_id,
                )
        decision = self.engine.decide(spec)
        try:
            validated = validate_args(spec, args)
        except ToolArgumentError as exc:
            return PreparedTool(
                name=name,
                spec=spec,
                args=dict(args or {}),
                decision=decision,
                status="invalid_args",
                error=str(exc),
                conversation_id=conversation_id,
            )

        prepared = PreparedTool(
            name=name, spec=spec, args=validated, decision=decision, conversation_id=conversation_id
        )
        if decision.level == "confirm":
            prepared.pending = self.confirmations.create(
                tool=spec.name,
                risk=spec.risk,
                args=validated,
                reason=decision.reason,
                description=spec.description,
                conversation_id=conversation_id,
            )
        return prepared

    async def wait(self, prepared: PreparedTool, *, timeout_s: float | None = None) -> bool:
        """Await the user's answer for a confirmation-needing request."""
        if prepared.pending is None:
            return prepared.decision.level == "allow"
        return await self.confirmations.wait(prepared.pending.id, timeout_s=timeout_s)

    # -------------------------------------------------------------------- run
    async def run(self, prepared: PreparedTool, *, approved: bool | None = None) -> ExecutionResult:
        """Execute a prepared request (logging every outcome, PRD §43)."""
        if prepared.status is not None:
            return self._finish(prepared, status=prepared.status, error=prepared.error)

        level = prepared.decision.level
        if level == "deny":
            return self._finish(
                prepared,
                status="denied",
                error=f"denied by policy: {prepared.decision.reason}",
            )
        if level == "confirm" and approved is not True:
            return self._finish(
                prepared,
                status="denied",
                error="the user declined this action",
            )

        tool = self.registry.get(prepared.name)
        spec = prepared.spec
        if tool is None or spec is None:
            return self._finish(prepared, status="error", error="tool is not registered")

        ctx = ToolContext(self.settings, conversation_id=prepared.conversation_id)
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.run(prepared.args, ctx), timeout=self.settings.tools.timeout_s
            )
        except TimeoutError:
            return self._finish(
                prepared,
                status="timeout",
                error=f"timed out after {self.settings.tools.timeout_s:g}s",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except ToolArgumentError as exc:
            return self._finish(
                prepared,
                status="invalid_args",
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except ToolError as exc:
            return self._finish(
                prepared,
                status="error",
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a tool must not crash the chat
            logger.exception("tool_crashed", extra={"tool": prepared.name})
            return self._finish(
                prepared,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        if not result.ok:
            return self._finish(
                prepared,
                status="error",
                error=result.error or "tool reported failure",
                output=result.output,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        return self._finish(
            prepared,
            status="ok",
            output=result.output,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def execute(
        self, name: str, args: dict[str, Any] | None, *, conversation_id: str | None = None
    ) -> ExecutionResult:
        """Prepare + (if needed) wait for confirmation + run, in one call."""
        prepared = self.prepare(name, args, conversation_id=conversation_id)
        if prepared.needs_confirmation:
            approved = await self.wait(prepared)
        else:
            approved = None
        return await self.run(prepared, approved=approved)

    # ------------------------------------------------------------------ log
    def _finish(
        self,
        prepared: PreparedTool,
        *,
        status: ExecutionStatus,
        error: str | None = None,
        output: str = "",
        duration_ms: float | None = None,
    ) -> ExecutionResult:
        spec = prepared.spec
        permission: PermissionLevel | str = prepared.decision.level if spec is not None else "n/a"
        result = ExecutionResult(
            tool=prepared.name,
            status=status,
            output=output,
            error=error,
            duration_ms=None if duration_ms is None else round(duration_ms, 2),
            args=prepared.args,
            risk=spec.risk if spec else "low",
            permission=permission,  # type: ignore[arg-type]
            permission_reason=prepared.decision.reason,
        )
        self._log(prepared, result)
        if prepared.pending is not None:
            self.confirmations.forget(prepared.pending.id)
        return result

    def _log(self, prepared: PreparedTool, result: ExecutionResult) -> None:
        result_name = {
            "ok": "success",
            "error": "error",
            "denied": "denied",
            "timeout": "timeout",
            "invalid_args": "invalid_args",
        }[result.status]
        try:
            append_log(
                self.settings,
                build_entry(
                    tool=result.tool,
                    risk=result.risk,
                    permission=str(result.permission),
                    result=result_name,
                    args=prepared.args,
                    output=result.output,
                    error=result.error,
                    duration_ms=result.duration_ms,
                ),
            )
        except OSError:  # noqa: PERF203 - logging must never break execution
            logger.warning("tool_log_write_failed", extra={"tool": result.tool})


_executor: ToolExecutor | None = None
_executor_key: tuple | None = None


def _executor_cache_key(settings: Settings) -> tuple:
    from luxion.tools.permissions import _engine_cache_key
    from luxion.tools.registry import _cache_key

    return (*_cache_key(settings), *_engine_cache_key(settings), settings.tools.timeout_s)


def get_executor(settings: Settings | None = None) -> ToolExecutor:
    """Process-wide executor bound to the current registry/engine."""
    global _executor, _executor_key
    from luxion.config.settings import get_settings
    from luxion.tools.permissions import get_engine
    from luxion.tools.registry import get_registry

    resolved = settings or get_settings()
    key = _executor_cache_key(resolved)
    if _executor is None or _executor_key != key:
        _executor = ToolExecutor(get_registry(resolved), get_engine(resolved), resolved)
        _executor_key = key
    return _executor


def reset_executor() -> None:
    global _executor, _executor_key
    _executor = None
    _executor_key = None
