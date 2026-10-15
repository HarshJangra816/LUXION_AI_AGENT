"""Coding-agent layer (PRD §34, §35, Phase 8).

Repository analysis, literal code search, a sandboxed command runner and the
git/GitHub helpers behind the ``code`` tool family. Imports ``tools`` never the
reverse (same direction rule as ``luxion.repository``).
"""

from __future__ import annotations

from luxion.coding.analyzer import ProjectAnalysis, analyze_project
from luxion.coding.gitops import (
    GitResult,
    clone_repository,
    git_available,
    git_commit,
    git_diff,
    git_log,
    git_status,
    github_cli_available,
    list_pull_requests,
)
from luxion.coding.search import GrepHit, grep_files
from luxion.coding.terminal import CommandResult, check_blocked, run_command

__all__ = [
    "CommandResult",
    "GitResult",
    "GrepHit",
    "ProjectAnalysis",
    "analyze_project",
    "check_blocked",
    "clone_repository",
    "git_available",
    "git_commit",
    "git_diff",
    "git_log",
    "git_status",
    "github_cli_available",
    "grep_files",
    "list_pull_requests",
    "run_command",
]
