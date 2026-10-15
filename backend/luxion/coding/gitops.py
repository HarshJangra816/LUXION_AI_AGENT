"""Git + GitHub helpers (PRD §34 "Using Git", "Creating commits",
"Working with GitHub", Phase 8).

Thin, honest wrappers over the ``git`` CLI — no libgit2/pygit2 dependency,
so whatever git the user already has (credentials, SSH keys, credential
helper, GPG signing) is exactly what Luxion uses. The GitHub side goes
through the official ``gh`` CLI when it is installed; without it the tools
degrade to a clear "install gh" message instead of a stack trace.

Every call runs with a scrubbed environment (see
:mod:`luxion.coding.terminal`) and a short timeout; commits never push —
``git_clone`` is the only network-writing operation, and it only writes
inside an approved workspace.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luxion.coding.terminal import scrubbed_env

#: Per-invocation limit for local git commands (status/diff are fast).
GIT_TIMEOUT_S = 60.0
CLONE_TIMEOUT_S = 300.0


class GitError(Exception):
    """A git/gh invocation failed; ``message`` is safe to show the model."""


@dataclass
class GitResult:
    """Outcome of one git call."""

    ok: bool
    output: str
    exit_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "exit_code": self.exit_code}


def git_available() -> bool:
    return shutil.which("git") is not None


def github_cli_available() -> bool:
    return shutil.which("gh") is not None


def _run_git(args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT_S) -> GitResult:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, our own helper
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=scrubbed_env(),
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git vanished mid-flight
        raise GitError("git is not installed (or not on PATH)") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args[:2])} timed out after {timeout:.0f}s") from exc
    output = (completed.stdout or "") + (completed.stderr or "")
    return GitResult(
        ok=completed.returncode == 0, output=output.strip(), exit_code=completed.returncode
    )


def _require(result: GitResult, action: str) -> GitResult:
    if not result.ok:
        raise GitError(f"git {action} failed: {result.output[:800] or '(no output)'}")
    return result


def git_status(root: Path) -> GitResult:
    """Branch + short change summary (``status --short --branch``)."""
    return _require(_run_git(["status", "--short", "--branch"], root), "status")


def git_diff(root: Path, *, staged: bool = False, path: str | None = None) -> GitResult:
    """Working-tree (or staged) diff; empty output means "no changes"."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    if path:
        args.extend(["--", path])
    return _require(_run_git(args, root), "diff")


def git_log(root: Path, limit: int = 10) -> GitResult:
    """Recent history, one line per commit."""
    limit = max(1, min(int(limit), 50))
    return _require(
        _run_git(["log", f"--oneline", f"-{limit}"], root),  # noqa: F541 - format string
        "log",
    )


def git_commit(root: Path, message: str, *, paths: list[str] | None = None) -> GitResult:
    """Stage ``paths`` (or everything) and commit. Never pushes.

    An empty ``git status`` short-circuit turns "nothing to commit" into a
    clean, model-readable error instead of git's exit code 1.
    """
    message = str(message).strip()
    if not message:
        raise GitError("commit message is empty")
    status = _run_git(["status", "--porcelain"], root)
    if status.ok and not status.output:
        raise GitError("nothing to commit — the working tree is clean")
    stage_args = ["add", "-A"] if not paths else ["add", "--", *(_clean_paths(paths))]
    _require(_run_git(stage_args, root), "add")
    return _require(_run_git(["commit", "-m", message], root), "commit")


def _clean_paths(paths: list[str]) -> list[str]:
    """Strip anything that could be read as a git option (``--force``)."""
    return [path for path in paths if not str(path).startswith("-")]


def clone_repository(url: str, destination: Path, *, depth: int = 1) -> GitResult:
    """Shallow-clone ``url`` into ``destination`` (must not exist yet)."""
    url = str(url).strip()
    if destination.exists():
        raise GitError(f"'{destination}' already exists — clone into a fresh directory")
    args = ["clone"]
    if depth and depth > 0:
        args.extend(["--depth", str(int(depth))])
    args.extend(["--", url, str(destination)])
    return _require(_run_git(args, destination.parent, timeout=CLONE_TIMEOUT_S), "clone")


def _run_gh(args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT_S) -> GitResult:
    if not github_cli_available():
        raise GitError(
            "GitHub CLI is not installed — install it from https://cli.github.com "
            "and run `gh auth login` to use GitHub features"
        )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, our own helper
            ["gh", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=scrubbed_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"gh {' '.join(args[:2])} timed out after {timeout:.0f}s") from exc
    output = (completed.stdout or "") + (completed.stderr or "")
    return GitResult(
        ok=completed.returncode == 0, output=output.strip(), exit_code=completed.returncode
    )


def list_pull_requests(root: Path, *, limit: int = 10, state: str = "open") -> GitResult:
    """Open (or closed/merged) PRs of the repo ``root`` belongs to, via ``gh``."""
    limit = max(1, min(int(limit), 50))
    if state not in ("open", "closed", "merged", "all"):
        raise GitError(f"unknown PR state '{state}' (use open, closed, merged or all)")
    raw = _require(
        _run_gh(
            [
                "pr",
                "list",
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,author,state,createdAt,url",
            ],
            root,
        ),
        "pr list",
    )
    try:
        pulls = json.loads(raw.output or "[]")
    except ValueError as exc:
        raise GitError(f"could not parse the GitHub response: {raw.output[:200]}") from exc
    return GitResult(
        ok=True,
        output=json.dumps(pulls, indent=2),
        exit_code=0,
    )
