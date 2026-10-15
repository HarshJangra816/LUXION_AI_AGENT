"""Coding-agent tools: analysis, grep, editing, the terminal and git (PRD §34, §35, Phase 8).

Hermetic where it can be: project fixtures live in ``tmp_path``, commands run
real (but tiny) shell jobs, git tests build a scratch repository. Nothing here
touches the developer's real repositories or installs anything.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from luxion.config.settings import Settings
from luxion.tools.base import ToolContext, ToolError
from luxion.tools.builtin.code import BUILTIN_TOOLS
from luxion.tools.registry import build_registry

TOOLS = {tool.spec.name: tool for tool in BUILTIN_TOOLS}


def asyncio_run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def _ctx(settings: Settings) -> ToolContext:
    return ToolContext(settings)


def _settings_in(path: Path) -> Settings:
    """Settings whose approved workspace is ``path`` (hermetic cwd)."""
    settings = Settings()
    settings.security.allowed_workspaces = [path]
    return settings


@pytest.fixture()
def py_project(tmp_path: Path) -> Path:
    """A tiny but real python project: marker, tests, a source file."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\n\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n", encoding="utf-8"
    )
    return tmp_path


# ------------------------------------------------------------------ registry
def test_every_code_tool_is_registered() -> None:
    assert set(TOOLS) == {
        "analyze_project",
        "grep_code",
        "edit_file",
        "run_command",
        "run_tests",
        "install_dependencies",
        "git_status",
        "git_diff",
        "git_commit",
        "git_clone",
        "github_prs",
    }
    names = set(build_registry(Settings()).names())
    assert set(TOOLS) <= names


def test_process_tools_declare_the_terminal_capability() -> None:
    """PRD §39: anything that executes is gated, not just risky."""
    gated = {name for name, tool in TOOLS.items() if tool.spec.requires == "terminal"}
    assert gated == {
        "run_command",
        "run_tests",
        "install_dependencies",
        "git_status",
        "git_diff",
        "git_commit",
        "git_clone",
        "github_prs",
    }
    # Pure filesystem work is workspace-scoped since Phase 3 — no capability.
    for name in ("analyze_project", "grep_code", "edit_file"):
        assert TOOLS[name].spec.requires is None


def test_risk_levels_follow_prd_section_20() -> None:
    risks = {name: tool.spec.risk for name, tool in TOOLS.items()}
    for name in ("analyze_project", "grep_code", "git_status", "git_diff", "github_prs"):
        assert risks[name] == "low", name
    assert risks["edit_file"] == "medium"
    for name in (
        "run_command",
        "run_tests",
        "install_dependencies",
        "git_commit",
        "git_clone",
    ):
        assert risks[name] == "high", name


def test_read_only_tools_declare_themselves() -> None:
    read_only = {name for name, tool in TOOLS.items() if tool.spec.read_only}
    assert read_only == {
        "analyze_project",
        "grep_code",
        "git_status",
        "git_diff",
        "github_prs",
    }


# ------------------------------------------------------------------ analyzer
def test_analyze_project_detects_a_python_repo(py_project: Path) -> None:
    result = asyncio_run(TOOLS["analyze_project"].run({}, _ctx(_settings_in(py_project))))

    assert result.ok is True
    assert "python" in result.data["project_types"]
    assert "python" in result.data["languages"]
    assert "pytest" in (result.data["test_command"] or "")
    assert result.data["package_manager"] == "pip"
    assert result.data["markers"] == ["pyproject.toml"]


def test_analyze_project_detects_node_commands(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "demo", "scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

    result = asyncio_run(TOOLS["analyze_project"].run({}, _ctx(_settings_in(tmp_path))))

    assert result.data["project_types"] == ["node"]
    assert result.data["package_manager"] == "npm"
    assert result.data["test_command"] == "npm test"
    assert result.data["build_command"] == "npm run build"
    assert result.data["lint_command"] == "npm run lint"


def test_analyze_project_flags_a_non_repository(tmp_path: Path) -> None:
    result = asyncio_run(TOOLS["analyze_project"].run({}, _ctx(_settings_in(tmp_path))))
    assert result.data["project_types"] == []
    assert any("no known project marker" in note for note in result.data["notes"])


def test_analyze_project_on_the_real_workspace() -> None:
    """Integration: Luxion itself — markers live one level down (backend/, frontend/)."""
    settings = Settings()
    result = asyncio_run(TOOLS["analyze_project"].run({}, _ctx(settings)))
    assert "python" in result.data["project_types"]
    assert "node" in result.data["project_types"]
    assert any("nested projects" in note for note in result.data["notes"])
    assert any("backend" in note for note in result.data["notes"])


# ---------------------------------------------------------------------- grep
def test_grep_code_finds_literal_lines(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["grep_code"].run({"pattern": "def greet"}, _ctx(_settings_in(py_project)))
    )
    assert result.ok is True
    assert len(result.data["hits"]) == 1
    hit = result.data["hits"][0]
    assert hit["path"].endswith("app.py")
    assert hit["line"] == 1


def test_grep_code_include_glob_narrows_files(py_project: Path) -> None:
    (tmp := py_project / "notes.md").write_text("def greet\n", encoding="utf-8")
    result = asyncio_run(
        TOOLS["grep_code"].run(
            {"pattern": "def greet", "include": "*.py"}, _ctx(_settings_in(py_project))
        )
    )
    assert [hit["path"] for hit in result.data["hits"]] == [str(py_project / "app.py")]
    assert tmp.exists()


def test_grep_code_regex_mode(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("value = 123\nother = 'abc'\n", encoding="utf-8")
    result = asyncio_run(
        TOOLS["grep_code"].run(
            {"pattern": r"value = \d+", "regex": True}, _ctx(_settings_in(tmp_path))
        )
    )
    assert len(result.data["hits"]) == 1


def test_grep_code_invalid_regex_is_a_tool_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="invalid regular expression"):
        asyncio_run(
            TOOLS["grep_code"].run({"pattern": "(", "regex": True}, _ctx(_settings_in(tmp_path)))
        )


def test_grep_code_skips_node_modules_and_binaries(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("needle\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG needle\x00")
    (tmp_path / "keep.txt").write_text("needle\n", encoding="utf-8")

    result = asyncio_run(
        TOOLS["grep_code"].run({"pattern": "needle"}, _ctx(_settings_in(tmp_path)))
    )
    assert [Path(hit["path"]).name for hit in result.data["hits"]] == ["keep.txt"]


def test_grep_code_no_hits_says_so(tmp_path: Path) -> None:
    result = asyncio_run(
        TOOLS["grep_code"].run({"pattern": "zzz-not-there"}, _ctx(_settings_in(tmp_path)))
    )
    assert result.ok is True
    assert result.data["hits"] == []
    assert "No lines match" in result.output


# ------------------------------------------------------------------ edit file
def test_edit_file_replaces_exactly_once(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["edit_file"].run(
            {
                "path": "app.py",
                "old_string": "hello ",
                "new_string": "hi ",
            },
            _ctx(_settings_in(py_project)),
        )
    )
    assert result.ok is True
    assert result.data["replacements"] == 1
    assert "hi " in (py_project / "app.py").read_text(encoding="utf-8")


def test_edit_file_rejects_an_ambiguous_fragment(py_project: Path) -> None:
    (py_project / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(ToolError, match="occurs 2 times"):
        asyncio_run(
            TOOLS["edit_file"].run(
                {"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"},
                _ctx(_settings_in(py_project)),
            )
        )


def test_edit_file_replace_all_is_explicit(py_project: Path) -> None:
    (py_project / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = asyncio_run(
        TOOLS["edit_file"].run(
            {
                "path": "app.py",
                "old_string": "x = 1",
                "new_string": "x = 2",
                "replace_all": True,
            },
            _ctx(_settings_in(py_project)),
        )
    )
    assert result.data["replacements"] == 2
    assert (py_project / "app.py").read_text(encoding="utf-8") == "x = 2\nx = 2\n"


def test_edit_file_missing_old_text_fails_loudly(py_project: Path) -> None:
    """A stale edit must never silently do nothing (PRD §36)."""
    with pytest.raises(ToolError, match="not found"):
        asyncio_run(
            TOOLS["edit_file"].run(
                {"path": "app.py", "old_string": "nope", "new_string": "yes"},
                _ctx(_settings_in(py_project)),
            )
        )


def test_edit_file_missing_file_points_at_write_file(py_project: Path) -> None:
    with pytest.raises(ToolError, match="write_file"):
        asyncio_run(
            TOOLS["edit_file"].run(
                {"path": "ghost.py", "old_string": "a", "new_string": "b"},
                _ctx(_settings_in(py_project)),
            )
        )


def test_edit_file_is_relative_to_the_workspace(py_project: Path) -> None:
    with pytest.raises(ToolError):
        asyncio_run(
            TOOLS["edit_file"].run(
                {
                    "path": str(py_project / ".." / "escape.py"),
                    "old_string": "a",
                    "new_string": "b",
                },
                _ctx(_settings_in(py_project)),
            )
        )


# ------------------------------------------------------------------- terminal
def test_run_command_reports_exit_code_and_output(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["run_command"].run(
            {"command": "echo hello-from-test"}, _ctx(_settings_in(py_project))
        )
    )
    assert result.ok is True
    assert result.data["exit_code"] == 0
    assert "hello-from-test" in result.data["stdout"]


def test_run_command_runs_inside_the_workspace(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["run_command"].run({"command": "cd"}, _ctx(_settings_in(py_project)))
    )
    # `cd` with no argument prints the cwd; Windows uses backslashes.
    assert str(py_project) in result.data["stdout"]


def test_run_command_failure_is_not_ok(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["run_command"].run({"command": "exit 3"}, _ctx(_settings_in(py_project)))
    )
    assert result.ok is False
    assert result.data["exit_code"] == 3


def test_run_command_refuses_destructive_commands(py_project: Path) -> None:
    """Backstop beyond the risk engine: no confirmation may allow these."""
    with pytest.raises(ToolError, match="destructive"):
        asyncio_run(
            TOOLS["run_command"].run({"command": "rm -rf /"}, _ctx(_settings_in(py_project)))
        )


def test_run_command_kills_a_hung_process(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["run_command"].run(
            {"command": 'python -c "import time; time.sleep(60)"', "timeout_s": 1},
            _ctx(_settings_in(py_project)),
        )
    )
    assert result.ok is False
    assert result.data["timed_out"] is True


def test_run_command_scrubs_secrets_from_the_child_environment(
    py_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD §57 rule 6: a child process must never see the user's keys."""
    monkeypatch.setenv("LUXION_TEST_FAKE_API_KEY", "sk-canary")
    monkeypatch.setenv("LUXION_TEST_HARMLESS", "kept")
    result = asyncio_run(
        TOOLS["run_command"].run(
            {
                "command": (
                    'python -c "import os; '
                    "print(os.environ.get('LUXION_TEST_FAKE_API_KEY', 'absent'), "
                    "os.environ.get('LUXION_TEST_HARMLESS', 'absent'))\""
                ),
            },
            _ctx(_settings_in(py_project)),
        )
    )
    assert "sk-canary" not in result.data["stdout"]
    assert "absent kept" in result.data["stdout"]


def test_run_command_clips_a_flood_of_output(py_project: Path) -> None:
    settings = _settings_in(py_project)
    settings.code.max_output_chars = 1000
    result = asyncio_run(
        TOOLS["run_command"].run({"command": "python -c \"print('x' * 50000)\""}, _ctx(settings))
    )
    assert result.data["clipped"] is True
    assert "output clipped" in result.data["stdout"]


# -------------------------------------------------------------------- tests
@pytest.fixture()
def venv_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make bare `python` resolve to this venv (which has pytest).

    The detected command is honest ``python -m pytest``; without an activated
    venv that is the *system* interpreter, which has no pytest installed.
    """
    scripts = str(Path(__import__("sys").executable).parent)
    monkeypatch.setenv("PATH", scripts + os.pathsep + os.environ.get("PATH", ""))


def test_run_tests_detects_and_runs_the_suite(py_project: Path, venv_on_path: None) -> None:
    result = asyncio_run(TOOLS["run_tests"].run({}, _ctx(_settings_in(py_project))))
    assert result.ok is True
    assert "pytest" in result.data["command"]
    assert "1 passed" in result.data["stdout"]
    assert result.data["failed"] is False


def test_run_tests_without_a_suite_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="no test command detected"):
        asyncio_run(TOOLS["run_tests"].run({}, _ctx(_settings_in(tmp_path))))


def test_run_tests_honours_an_explicit_command(py_project: Path) -> None:
    result = asyncio_run(
        TOOLS["run_tests"].run({"command": "echo custom-suite"}, _ctx(_settings_in(py_project)))
    )
    assert "custom-suite" in result.data["stdout"]


# ----------------------------------------------------------------- installs
def test_install_dependencies_detects_pip(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("# nothing yet\n", encoding="utf-8")
    result = asyncio_run(
        TOOLS["install_dependencies"].run(
            {"command": "echo would-install"}, _ctx(_settings_in(tmp_path))
        )
    )
    assert "would-install" in result.data["stdout"]


def test_install_dependencies_detection_for_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("# nothing yet\n", encoding="utf-8")
    # Detection is asserted without executing: no marker for a real install.
    from luxion.coding.analyzer import analyze_project
    from luxion.tools.builtin.code import _install_command

    command = _install_command(tmp_path, analyze_project(tmp_path))
    assert command == "python -m pip install -r requirements.txt"


def test_install_dependencies_unknown_stack_asks_for_a_command(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="no package manager detected"):
        asyncio_run(TOOLS["install_dependencies"].run({}, _ctx(_settings_in(tmp_path))))


# ----------------------------------------------------------------------- git
@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch repository with one commit and an identity that always works.

    The identity is patched into ``os.environ`` (not just the priming
    subprocesses') so the *tools'* scrubbed child env inherits it too.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Luxion Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@luxion.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Luxion Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@luxion.local")
    env = os.environ
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    (repo / "hello.txt").write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, env=env, check=True)
    return repo


def test_git_status_reports_the_branch_and_changes(git_repo: Path) -> None:
    (git_repo / "hello.txt").write_text("second\n", encoding="utf-8")
    result = asyncio_run(TOOLS["git_status"].run({}, _ctx(_settings_in(git_repo))))
    assert result.ok is True
    assert "main" in result.data["output"]
    assert "hello.txt" in result.data["output"]


def test_git_diff_shows_the_modification(git_repo: Path) -> None:
    (git_repo / "hello.txt").write_text("second\n", encoding="utf-8")
    result = asyncio_run(TOOLS["git_diff"].run({}, _ctx(_settings_in(git_repo))))
    assert "+second" in result.data["output"]


def test_git_commit_creates_a_commit(git_repo: Path) -> None:
    (git_repo / "hello.txt").write_text("second\n", encoding="utf-8")
    result = asyncio_run(
        TOOLS["git_commit"].run({"message": "change greeting"}, _ctx(_settings_in(git_repo)))
    )
    assert result.ok is True
    assert "change greeting" in result.data["head"]


def test_git_commit_on_a_clean_tree_fails_cleanly(git_repo: Path) -> None:
    with pytest.raises(ToolError, match="nothing to commit"):
        asyncio_run(TOOLS["git_commit"].run({"message": "noop"}, _ctx(_settings_in(git_repo))))


def test_git_clone_refuses_non_urls(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="git URL"):
        asyncio_run(
            TOOLS["git_clone"].run(
                {"url": "C:\\evil\\path", "destination": "clone-here"},
                _ctx(_settings_in(tmp_path)),
            )
        )


def test_git_clone_refuses_an_existing_destination(git_repo: Path, tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "taken").mkdir()
    with pytest.raises(ToolError, match="already exists"):
        asyncio_run(
            TOOLS["git_clone"].run(
                {"url": "https://example.invalid/x.git", "destination": "taken"},
                _ctx(_settings_in(parent)),
            )
        )


@pytest.mark.skipif(shutil.which("gh") is None, reason="GitHub CLI not installed")
def test_github_prs_needs_a_real_repository(git_repo: Path) -> None:
    # The scratch repo has no remote, so gh either errors (mapped to a clear
    # ToolError) or reports an empty list — both are acceptable outcomes.
    try:
        result = asyncio_run(TOOLS["github_prs"].run({}, _ctx(_settings_in(git_repo))))
        assert result.data["root"] == str(git_repo)
    except ToolError as exc:
        assert "gh" in str(exc).lower() or "git" in str(exc).lower()


# --------------------------------------------------------------------- gates
def test_disabled_master_switch_blocks_every_tool(py_project: Path) -> None:
    settings = _settings_in(py_project)
    settings.code.enabled = False
    ctx = _ctx(settings)
    for name, tool in TOOLS.items():
        with pytest.raises(ToolError, match="disabled"):
            asyncio_run(tool.run({}, ctx)), name
