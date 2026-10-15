"""Coding-agent tools (PRD §34, §35, Phase 8).

Eleven tools in five groups:

==============  ==========================================================
analysis        ``analyze_project`` (what is this repo, how do I test it)
search/edit     ``grep_code``, ``edit_file`` (``read_file``/``write_file``
                from Phase 3 cover the rest)
terminal        ``run_command``, ``run_tests``, ``install_dependencies``
git             ``git_status``, ``git_diff``, ``git_commit``, ``git_clone``
github          ``github_prs``
==============  ==========================================================

Risk follows §20 and the Phase 7 precedent: reading (analysis, grep, git
status/diff, PR list) is LOW and read-only; editing a source file is MEDIUM
(same as ``write_file``); anything that *executes* — commands, tests,
installs, commits, clones — is HIGH, so the default autonomy level asks the
user every time. Every process-spawning tool additionally declares
``requires="terminal"`` (the Phase 8 app consent, default **off**), so the
capability layer hard-blocks the whole family regardless of autonomy (§39).
Pure-filesystem tools (analyze, grep, edit) need no capability: they are
workspace-scoped like ``read_file`` since Phase 3.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from luxion.coding import gitops
from luxion.coding.analyzer import ProjectAnalysis, analyze_project
from luxion.coding.search import GrepHit, grep_files
from luxion.coding.terminal import (
    CommandBlockedError,
    CommandResult,
    check_blocked,
    run_command,
)
from luxion.tools.base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from luxion.tools.builtin.files import resolve_in_workspace

#: Every tool that spawns a process is gated on this capability (§39).
TERMINAL_CAPABILITY = "terminal"

_ANALYSIS_TAGS = [
    "code",
    "project",
    "analyze",
    "repository",
    "repo",
    "structure",
    "language",
    "setup",
    "stack",
    "discover",
]

_SEARCH_TAGS = ["code", "search", "grep", "find", "regex", "pattern", "lookup", "where"]

_EDIT_TAGS = ["edit", "file", "change", "modify", "patch", "fix", "replace", "update"]

_RUN_TAGS = [
    "run",
    "command",
    "shell",
    "terminal",
    "execute",
    "test",
    "pytest",
    "npm",
    "install",
    "dependencies",
    "build",
]

_GIT_TAGS = ["git", "commit", "diff", "status", "repository", "version", "control", "clone"]

_GITHUB_TAGS = ["github", "pull request", "pr", "review", "remote", "merge"]


def _require_enabled(ctx: ToolContext) -> None:
    if not ctx.settings.code.enabled:
        raise ToolError(
            "coding tools are disabled — turn them on in Settings → Coding",
            code="disabled",
        )


def _workspace_root(ctx: ToolContext, raw: str | None) -> Path:
    """Resolve the directory a tool works in (default: first workspace)."""
    if raw:
        path = resolve_in_workspace(raw, ctx)
        if not path.is_dir():
            raise ToolError(f"'{path}' is not a directory")
        return path
    roots = ctx.workspaces
    if not roots:
        raise ToolError("no approved workspace is configured (LUXION_SECURITY__ALLOWED_WORKSPACES)")
    return roots[0]


def _timeout(ctx: ToolContext, override: Any) -> float:
    if override is None:
        return ctx.settings.code.command_timeout_s
    try:
        return max(1.0, min(float(override), 900.0))
    except (TypeError, ValueError) as exc:
        raise ToolError(f"invalid timeout: {override!r}") from exc


def _describe(result: CommandResult) -> str:
    """Model-facing rendering: exit code first, then the output tail."""
    head = f"exit code {result.exit_code}" if result.exit_code is not None else "killed"
    if result.timed_out:
        head += " (timed out — the process tree was killed)"
    body = result.stdout
    if result.stderr.strip():
        body += ("\n" if body else "") + f"[stderr]\n{result.stderr}"
    if not body.strip():
        body = "(no output)"
    return f"{head}, {result.duration_s:.1f}s\n{body}"


def _data(result: CommandResult) -> dict[str, Any]:
    return result.as_dict()


# ------------------------------------------------------------------ analysis
class AnalyzeProject(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="analyze_project",
            description=(
                "Analyze a project directory and report what it is: languages, "
                "project type (python/node/rust/go/…), package manager, the "
                "test/build/lint/run commands, entry points and source layout. "
                "Cheap and read-only — call it before planning work in an "
                "unfamiliar repository. Optional 'path' (default: the approved "
                "workspace)."
            ),
            risk="low",
            category="code",
            tags=_ANALYSIS_TAGS,
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project directory (default: workspace root).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        root = _workspace_root(ctx, args.get("path"))
        analysis: ProjectAnalysis = await asyncio.to_thread(analyze_project, root)
        return ToolResult(output=analysis.summary(), data=analysis.as_dict())


# --------------------------------------------------------------------- search
class GrepCode(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="grep_code",
            description=(
                "Literal (or regex) search across the project's text files: "
                "returns file:line hits with the matching lines. Use it when "
                "you already know the exact symbol, identifier or error text "
                "you need to find ('def flush_stream', 'AttributeError'). For "
                "conceptual questions use search_code instead. Skips binaries, "
                ".git, node_modules and other build directories."
            ),
            risk="low",
            category="code",
            tags=_SEARCH_TAGS,
            read_only=True,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Text or regex to look for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search (default: workspace root).",
                    },
                    "include": {
                        "type": "string",
                        "description": "Filename glob, e.g. '*.py' or 'test_*.py'.",
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "Treat the pattern as a regular expression.",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case-insensitive match.",
                    },
                    "max_hits": {
                        "type": "integer",
                        "description": "Stop after this many hits (default 50, max 200).",
                    },
                },
                "required": ["pattern"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        pattern = str(args.get("pattern") or "")
        if not pattern:
            raise ToolError("'pattern' must not be empty")
        root = _workspace_root(ctx, args.get("path"))
        try:
            hits: list[GrepHit] = await asyncio.to_thread(
                grep_files,
                root,
                pattern,
                regex=bool(args.get("regex")),
                ignore_case=bool(args.get("ignore_case")),
                include=(str(args["include"]) if args.get("include") else None),
                max_hits=int(args.get("max_hits") or 50),
            )
        except ValueError as exc:  # invalid regex
            raise ToolError(str(exc)) from exc
        if not hits:
            return ToolResult(
                output=f"No lines match '{pattern}' under {root}.",
                data={"pattern": pattern, "root": str(root), "hits": []},
            )
        try:
            shown = [f"{Path(hit.path).relative_to(root)}:{hit.line}: {hit.text}" for hit in hits]
        except ValueError:  # pragma: no cover - hit outside root (symlink)
            shown = [f"{hit.path}:{hit.line}: {hit.text}" for hit in hits]
        return ToolResult(
            output="\n".join(shown),
            data={
                "pattern": pattern,
                "root": str(root),
                "hits": [hit.as_dict() for hit in hits],
            },
        )


# ----------------------------------------------------------------- edit file
class EditFile(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="edit_file",
            description=(
                "Replace an exact text fragment in a file (surgical edit — "
                "preferred over write_file for code changes, which would "
                "rewrite the whole file). 'old_string' must appear exactly "
                "once unless 'replace_all' is true; include a few surrounding "
                "lines when the fragment alone is ambiguous. Raises an error "
                "if the old text is not found, so a stale edit never silently "
                "does nothing."
            ),
            risk="medium",
            category="code",
            tags=_EDIT_TAGS,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative file path.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to find (must match verbatim).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text (empty string deletes).",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence instead of requiring one.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        path = resolve_in_workspace(str(args["path"]), ctx)
        if not path.exists():
            raise ToolError(f"file not found: {path} (use write_file to create it)")
        if path.is_dir():
            raise ToolError(f"'{path}' is a directory")
        old = str(args["old_string"])
        new = str(args["new_string"])
        if old == new:
            raise ToolError("old_string and new_string are identical — nothing to do")
        if not old:
            raise ToolError("old_string is empty — edit_file cannot insert from nothing")

        text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        count = text.count(old)
        if count == 0:
            raise ToolError(
                f"old_string not found in {path} — re-read the file; it may have "
                "changed since you last saw it"
            )
        replace_all = bool(args.get("replace_all"))
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string occurs {count} times in {path} — add surrounding "
                "lines to make it unique, or set replace_all=true"
            )
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        await asyncio.to_thread(path.write_text, updated, encoding="utf-8")
        if replace_all:
            plural = "s" if count != 1 else ""
            action = f"replaced {count} occurrence{plural}"
        else:
            action = "edited"
        return ToolResult(
            output=f"{action} in {path}",
            data={"path": str(path), "replacements": count if replace_all else 1},
        )


# ------------------------------------------------------------------- terminal
def _run_in(
    ctx: ToolContext,
    command: str,
    cwd: Path,
    timeout_s: float | None = None,
) -> CommandResult:
    try:
        check_blocked(command)
    except CommandBlockedError as exc:
        raise ToolError(str(exc), code="blocked") from exc
    try:
        return run_command(
            command,
            cwd=cwd,
            timeout_s=_timeout(ctx, timeout_s),
            max_output=ctx.settings.code.max_output_chars,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


class RunCommand(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_command",
            description=(
                "Run a shell command inside the project workspace and return "
                "its exit code and output. Use it to build, run, inspect logs, "
                "or do anything else a terminal does; prefer run_tests / "
                "install_dependencies for those specific jobs. Output is "
                "clipped and the command times out — a destructive command "
                "list is refused outright."
            ),
            risk="high",
            category="code",
            tags=_RUN_TAGS,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run."},
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (default: workspace root).",
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": "Wall-clock limit (default from Settings, max 900).",
                    },
                },
                "required": ["command"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        command = str(args.get("command") or "").strip()
        if not command:
            raise ToolError("'command' must not be empty")
        cwd = _workspace_root(ctx, args.get("cwd"))
        result = await asyncio.to_thread(_run_in, ctx, command, cwd, args.get("timeout_s"))
        return ToolResult(output=_describe(result), data=_data(result), ok=result.ok)


class RunTests(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_tests",
            description=(
                "Run the project's test suite (detected automatically: pytest, "
                "npm/pnpm/yarn test, cargo test, go test, …) or an explicit "
                "command. Returns the exit code plus the tail of the output, "
                "with failures called out — the first step of the fix loop in "
                "the coding workflow."
            ),
            risk="high",
            category="code",
            tags=_RUN_TAGS,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Override the detected test command.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Project directory (default: workspace root).",
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": "Wall-clock limit (default from Settings, max 900).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        cwd = _workspace_root(ctx, args.get("cwd"))
        command = str(args.get("command") or "").strip()
        if not command:
            analysis = await asyncio.to_thread(analyze_project, cwd)
            command = analysis.test_command or ""
            if not command:
                raise ToolError(
                    f"no test command detected in {cwd} — pass 'command' (e.g. 'python -m pytest')"
                )
        result = await asyncio.to_thread(_run_in, ctx, command, cwd, args.get("timeout_s"))
        data = _data(result)
        data["failed"] = not result.ok
        return ToolResult(output=_describe(result), data=data, ok=result.ok)


class InstallDependencies(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="install_dependencies",
            description=(
                "Install the project's dependencies with its own package "
                "manager (pip/poetry/uv, npm/pnpm/yarn/bun, cargo, go, maven, "
                "gradle — detected from the project markers). An explicit "
                "'command' overrides the detection."
            ),
            risk="high",
            category="code",
            tags=_RUN_TAGS,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "cwd": {
                        "type": "string",
                        "description": "Project directory (default: workspace root).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Override the detected install command.",
                    },
                    "timeout_s": {
                        "type": "number",
                        "description": "Wall-clock limit (default from Settings, max 900).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        cwd = _workspace_root(ctx, args.get("cwd"))
        command = str(args.get("command") or "").strip()
        if not command:
            analysis = await asyncio.to_thread(analyze_project, cwd)
            command = _install_command(cwd, analysis)
            if not command:
                raise ToolError(
                    f"no package manager detected in {cwd} — pass 'command' "
                    "(e.g. 'pip install -r requirements.txt')"
                )
        result = await asyncio.to_thread(_run_in, ctx, command, cwd, args.get("timeout_s"))
        return ToolResult(output=_describe(result), data=_data(result), ok=result.ok)


def _install_command(cwd: Path, analysis: ProjectAnalysis) -> str | None:
    """The install command for the detected stack (None when unknown)."""
    manager = analysis.package_manager
    if manager == "pip":
        if (cwd / "requirements.txt").exists():
            return "python -m pip install -r requirements.txt"
        if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
            return "python -m pip install -e ."
        return None
    if manager == "poetry":
        return "poetry install"
    if manager == "uv":
        return "uv sync"
    if manager == "pipenv":
        return "pipenv install"
    if manager in ("npm", "pnpm", "yarn", "bun"):
        return manager if manager != "npm" else "npm install"
    if manager == "cargo":
        return "cargo fetch"
    if manager == "go":
        return "go mod download"
    if manager == "maven":
        return "mvn dependency:resolve"
    if manager == "gradle":
        return "./gradlew dependencies" if (cwd / "gradlew").exists() else "gradle dependencies"
    if manager == "bundler":
        return "bundle install"
    if manager == "composer":
        return "composer install"
    return None


# ------------------------------------------------------------------------ git
def _git_error(exc: gitops.GitError) -> ToolError:
    return ToolError(str(exc), code="git_error")


class GitStatus(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_status",
            description=(
                "Current branch and working-tree state (staged / modified / "
                "untracked files) of a git repository. Check this before and "
                "after edits so you know what your change would commit."
            ),
            risk="low",
            category="code",
            tags=_GIT_TAGS,
            read_only=True,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository directory (default: workspace root).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        if not gitops.git_available():
            raise ToolError("git is not installed (or not on PATH)")
        root = _workspace_root(ctx, args.get("path"))
        try:
            status = await asyncio.to_thread(gitops.git_status, root)
        except gitops.GitError as exc:
            raise _git_error(exc) from exc
        return ToolResult(
            output=status.output or "(clean)",
            data={"root": str(root), **status.as_dict()},
        )


class GitDiff(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_diff",
            description=(
                "Unified diff of the working tree (or the staging area with "
                "staged=true), optionally for one path. Empty output means no "
                "changes. Use it to review your own edits before committing."
            ),
            risk="low",
            category="code",
            tags=_GIT_TAGS,
            read_only=True,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository or file path (default: workspace root).",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Diff the staging area instead of the working tree.",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        if not gitops.git_available():
            raise ToolError("git is not installed (or not on PATH)")
        root = _workspace_root(ctx, args.get("path"))
        try:
            diff = await asyncio.to_thread(gitops.git_diff, root, staged=bool(args.get("staged")))
        except gitops.GitError as exc:
            raise _git_error(exc) from exc
        output = diff.output or "(no changes)"
        return ToolResult(output=output, data={"root": str(root), **diff.as_dict()})


class GitCommit(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_commit",
            description=(
                "Stage changes (everything, or the listed paths) and create a "
                "commit with the given message. Never pushes. Fails cleanly "
                "when the working tree is already clean."
            ),
            risk="high",
            category="code",
            tags=_GIT_TAGS,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message."},
                    "path": {
                        "type": "string",
                        "description": "Repository directory (default: workspace root).",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Stage only these paths (default: everything).",
                    },
                },
                "required": ["message"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        if not gitops.git_available():
            raise ToolError("git is not installed (or not on PATH)")
        root = _workspace_root(ctx, args.get("path"))
        message = str(args.get("message") or "").strip()
        if not message:
            raise ToolError("'message' must not be empty")
        raw_paths = args.get("paths")
        paths = [str(item) for item in raw_paths] if isinstance(raw_paths, list) else None
        try:
            commit = await asyncio.to_thread(gitops.git_commit, root, message, paths=paths)
        except gitops.GitError as exc:
            raise _git_error(exc) from exc
        log = await asyncio.to_thread(gitops.git_log, root, 1)
        return ToolResult(
            output=commit.output or "committed",
            data={"root": str(root), "message": message, "head": log.output, **commit.as_dict()},
        )


class GitClone(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_clone",
            description=(
                "Shallow-clone a git repository (https/ssh URL) into a new "
                "directory inside the workspace, so the coding tools can work "
                "on it. The destination must not exist yet."
            ),
            risk="high",
            category="code",
            tags=_GIT_TAGS,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Repository URL to clone."},
                    "destination": {
                        "type": "string",
                        "description": "New directory inside the workspace.",
                    },
                },
                "required": ["url", "destination"],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        if not gitops.git_available():
            raise ToolError("git is not installed (or not on PATH)")
        url = str(args.get("url") or "").strip()
        if not url:
            raise ToolError("'url' must not be empty")
        if not (
            url.startswith(("http://", "https://", "ssh://", "git://", "git@"))
            or url.endswith(".git")
        ):
            raise ToolError("'url' must be an https/ssh git URL")
        destination = resolve_in_workspace(str(args.get("destination") or ""), ctx)
        try:
            clone = await asyncio.to_thread(gitops.clone_repository, url, destination)
        except gitops.GitError as exc:
            raise _git_error(exc) from exc
        analysis = await asyncio.to_thread(analyze_project, destination)
        return ToolResult(
            output=f"cloned into {destination}\n{analysis.summary()}",
            data={
                "destination": str(destination),
                **clone.as_dict(),
                "project": analysis.as_dict(),
            },
        )


# --------------------------------------------------------------------- github
class GithubPrs(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="github_prs",
            description=(
                "List the repository's pull requests through the GitHub CLI "
                "(gh): number, title, author, state, URL. Requires gh to be "
                "installed and authed; errors clearly when it is not."
            ),
            risk="low",
            category="code",
            tags=_GITHUB_TAGS,
            read_only=True,
            requires=TERMINAL_CAPABILITY,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository directory (default: workspace root).",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "merged", "all"],
                        "description": "Which PRs to list (default open).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many PRs (default 10, max 50).",
                    },
                },
                "required": [],
            },
        )

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        _require_enabled(ctx)
        root = _workspace_root(ctx, args.get("path"))
        state = str(args.get("state") or "open")
        limit = int(args.get("limit") or 10)
        try:
            result = await asyncio.to_thread(
                gitops.list_pull_requests, root, limit=limit, state=state
            )
        except gitops.GitError as exc:
            raise _git_error(exc) from exc
        return ToolResult(output=result.output or "(no pull requests)", data={"root": str(root)})


BUILTIN_TOOLS: list[Tool] = [
    AnalyzeProject(),
    GrepCode(),
    EditFile(),
    RunCommand(),
    RunTests(),
    InstallDependencies(),
    GitStatus(),
    GitDiff(),
    GitCommit(),
    GitClone(),
    GithubPrs(),
]
