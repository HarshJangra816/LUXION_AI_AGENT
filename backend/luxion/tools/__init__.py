"""Tool framework (Phase 3, PRD §3.1 / §18-21).

    tool request → registry → permission engine → executor → audit log

Import surface for the rest of the backend; the agent loop in
:mod:`luxion.services.chat` only needs :func:`get_executor`.
"""

from __future__ import annotations

from luxion.tools.base import (
    PermissionLevel,
    Tool,
    ToolArgumentError,
    ToolContext,
    ToolError,
    ToolResult,
    ToolRisk,
    ToolSpec,
    validate_args,
)
from luxion.tools.confirmations import ConfirmationManager, get_confirmations, reset_confirmations
from luxion.tools.executor import ExecutionResult, ToolExecutor, get_executor, reset_executor
from luxion.tools.permissions import (
    AUTONOMY_MATRIX,
    PermissionDecision,
    PermissionEngine,
    get_engine,
    reset_engine,
)
from luxion.tools.registry import ToolRegistry, build_registry, get_registry, reset_registry
from luxion.tools.router import select_tools

__all__ = [
    "AUTONOMY_MATRIX",
    "ConfirmationManager",
    "ExecutionResult",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionLevel",
    "Tool",
    "ToolArgumentError",
    "ToolContext",
    "ToolError",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "ToolRisk",
    "ToolSpec",
    "build_registry",
    "get_confirmations",
    "get_engine",
    "get_executor",
    "get_registry",
    "reset_confirmations",
    "reset_engine",
    "reset_executor",
    "reset_registry",
    "select_tools",
    "validate_args",
]
