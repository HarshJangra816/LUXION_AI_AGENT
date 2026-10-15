"""Repository analyzer (PRD §34, §35 — "Repository Discovery / Project Analysis").

Answers "what is this project and how do I work on it?" without burning
context on raw files: languages, project type, the package manager, the
test/build/lint commands to run, git presence and the source layout.

Everything here is a cheap filesystem probe — no subprocesses, no network —
so ``analyze_project`` can be called on every coding turn. Results are
returned as a plain dict for the model *and* a compact one-line summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Directories that never contain primary project sources.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "target",
        ".next",
        ".nuxt",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "coverage",
        ".idea",
        ".vscode",
        "obj",
        "bin",
        "out",
        ".cache",
    }
)

#: Marker file → (project type, language).
MARKERS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("python", "python"),
    "setup.py": ("python", "python"),
    "requirements.txt": ("python", "python"),
    "package.json": ("node", "javascript"),
    "Cargo.toml": ("rust", "rust"),
    "go.mod": ("go", "go"),
    "pom.xml": ("java", "java"),
    "build.gradle": ("java", "java"),
    "build.gradle.kts": ("java", "kotlin"),
    "Gemfile": ("ruby", "ruby"),
    "composer.json": ("php", "php"),
    "CMakeLists.txt": ("c++", "c++"),
    "Makefile": ("make", "make"),
}

#: File suffix → language (used for the language mix).
SUFFIX_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "c++",
    ".hpp": "c++",
    ".cs": "c#",
    ".swift": "swift",
    ".sql": "sql",
    ".sh": "shell",
    ".ps1": "shell",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
}

#: How many files the language scan looks at before stopping.
MAX_SCAN_FILES = 4000


@dataclass
class ProjectAnalysis:
    """Structured answer to "what is this repository?"."""

    root: str
    project_types: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    package_manager: str | None = None
    test_command: str | None = None
    build_command: str | None = None
    lint_command: str | None = None
    run_command: str | None = None
    entry_points: list[str] = field(default_factory=list)
    source_dirs: list[str] = field(default_factory=list)
    is_git: bool = False
    markers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "project_types": self.project_types,
            "languages": self.languages,
            "package_manager": self.package_manager,
            "test_command": self.test_command,
            "build_command": self.build_command,
            "lint_command": self.lint_command,
            "run_command": self.run_command,
            "entry_points": self.entry_points,
            "source_dirs": self.source_dirs,
            "is_git": self.is_git,
            "markers": self.markers,
            "notes": self.notes,
        }

    def summary(self) -> str:
        """One compact paragraph — what the model reads first."""
        kinds = "/".join(self.project_types) or "unknown"
        langs = ", ".join(f"{name} ({count})" for name, count in list(self.languages.items())[:4])
        parts = [f"{kinds} project", f"languages: {langs or 'unknown'}"]
        if self.package_manager:
            parts.append(f"package manager: {self.package_manager}")
        for label, command in (
            ("test", self.test_command),
            ("build", self.build_command),
            ("lint", self.lint_command),
            ("run", self.run_command),
        ):
            if command:
                parts.append(f"{label}: `{command}`")
        if self.is_git:
            parts.append("git repository")
        if self.source_dirs:
            parts.append(f"source dirs: {', '.join(self.source_dirs)}")
        return "; ".join(parts)


def _read_text(path: Path, limit: int = 256 * 1024) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _python_commands(root: Path, pyproject: str) -> tuple[str | None, str | None, str | None]:
    """(test, build, lint) commands inferred from a pyproject.toml."""
    test = build = lint = None
    if "[tool.pytest" in pyproject or (root / "tests").is_dir() or (root / "test").is_dir():
        test = "python -m pytest -q"
    if "[tool.ruff" in pyproject:
        lint = "ruff check ."
    if "[build-system]" in pyproject:
        build = "python -m build"
    if not test and (root / "manage.py").exists():
        test = "python manage.py test"
    return test, build, lint


def _node_commands(root: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """(test, build, lint, run) from package.json scripts."""
    data = json.loads(_read_text(root / "package.json") or "{}")
    if not isinstance(data, dict):
        return None, None, None, None
    scripts = data.get("scripts") or {}
    if not isinstance(scripts, dict):
        scripts = {}
    package_manager = _node_package_manager(root)

    def script(name: str) -> str | None:
        if name not in scripts:
            return None
        if package_manager == "yarn":
            return f"yarn {name}"
        if package_manager == "pnpm":
            return f"pnpm run {name}"
        if package_manager == "bun":
            return f"bun run {name}"
        return f"npm run {name}"

    test = f"{package_manager or 'npm'} test" if "test" in scripts else None
    return test, script("build"), script("lint"), script("start")


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    return "npm"


def _package_manager(root: Path, types: list[str]) -> str | None:
    if "python" in types:
        if (root / "uv.lock").exists():
            return "uv"
        if (root / "poetry.lock").exists():
            return "poetry"
        if (root / "Pipfile").exists():
            return "pipenv"
        return "pip"
    if "node" in types:
        return _node_package_manager(root)
    if "rust" in types:
        return "cargo"
    if "go" in types:
        return "go"
    if "java" in types:
        gradle = ("build.gradle", "build.gradle.kts")
        return "gradle" if any((root / name).exists() for name in gradle) else "maven"
    if "ruby" in types:
        return "bundler"
    if "php" in types:
        return "composer"
    return None


def _language_mix(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen = 0
    stack = [root]
    while stack and seen < MAX_SCAN_FILES:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if seen >= MAX_SCAN_FILES:
                break
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
                continue
            seen += 1
            language = SUFFIX_LANGUAGES.get(entry.suffix.lower())
            if language:
                counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def _source_dirs(root: Path, languages: dict[str, int]) -> list[str]:
    """Top-level dirs that hold the majority of the code (src, app, lib, …)."""
    wanted = {"python", "javascript", "typescript", "rust", "go", "java", "c++", "c"}
    interesting = [name for name in languages if name in wanted][:3]
    dirs: dict[str, int] = {}
    for child in root.iterdir() if root.is_dir() else []:
        if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith("."):
            count = _count_files(child, interesting)
            if count:
                dirs[child.name] = count
    ranked = sorted(dirs.items(), key=lambda item: item[1], reverse=True)
    return [name for name, count in ranked if count >= 3][:5]


def _count_files(directory: Path, languages: list[str], depth: int = 3) -> int:
    if depth < 0:
        return 0
    total = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.is_dir():
            if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                total += _count_files(entry, languages, depth - 1)
        elif SUFFIX_LANGUAGES.get(entry.suffix.lower()) in languages:
            total += 1
    return total


def _entry_points(root: Path, types: list[str]) -> list[str]:
    candidates = [
        "main.py",
        "app.py",
        "manage.py",
        "cli.py",
        "src/main.py",
        "src/app.py",
        "index.js",
        "index.ts",
        "src/index.js",
        "src/index.ts",
        "src/main.rs",
        "src/lib.rs",
        "main.go",
        "cmd",
        "src/main.cpp",
        "Program.cs",
    ]
    found = [name for name in candidates if (root / name).exists()]
    return found[:8]


def _nested_projects(root: Path) -> list[tuple[str, str]]:
    """Markers found one level down (monorepo layout: backend/, frontend/, …).

    A workspace root like this repository's own holds ``backend/pyproject.toml``
    and ``frontend/package.json`` but no marker at the top — reporting "not a
    repository" there would be wrong and useless.
    """
    found: list[tuple[str, str]] = []
    try:
        children = sorted(child for child in root.iterdir() if child.is_dir())
    except OSError:
        return found
    for child in children:
        if child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        for marker, (kind, _language) in MARKERS.items():
            if (child / marker).exists():
                found.append((child.name, kind))
                break
        if len(found) >= 8:
            break
    return found


def analyze_project(root: Path) -> ProjectAnalysis:
    """Analyze the repository at ``root`` (cheap, read-only, never raises)."""
    root = Path(root)
    analysis = ProjectAnalysis(root=str(root))
    if not root.is_dir():
        analysis.notes.append(f"'{root}' is not a directory")
        return analysis

    for marker, (kind, _language) in MARKERS.items():
        if (root / marker).exists():
            analysis.markers.append(marker)
            if kind not in analysis.project_types:
                analysis.project_types.append(kind)

    analysis.languages = _language_mix(root)
    analysis.is_git = (root / ".git").exists()
    analysis.package_manager = _package_manager(root, analysis.project_types)
    analysis.entry_points = _entry_points(root, analysis.project_types)
    analysis.source_dirs = _source_dirs(root, analysis.languages)

    if "python" in analysis.project_types:
        pyproject = _read_text(root / "pyproject.toml")
        analysis.test_command, analysis.build_command, analysis.lint_command = _python_commands(
            root, pyproject
        )
        if (root / "manage.py").exists():
            analysis.run_command = "python manage.py runserver"
    elif "node" in analysis.project_types:
        node = _node_commands(root)
        (
            analysis.test_command,
            analysis.build_command,
            analysis.lint_command,
            analysis.run_command,
        ) = node
    elif "rust" in analysis.project_types:
        analysis.test_command = "cargo test"
        analysis.build_command = "cargo build"
        analysis.lint_command = "cargo clippy" if (root / "clippy.toml").exists() else None
    elif "go" in analysis.project_types:
        analysis.test_command = "go test ./..."
        analysis.build_command = "go build ./..."
    elif "java" in analysis.project_types:
        if analysis.package_manager == "gradle":
            wrapper = (root / "gradlew").exists()
            analysis.test_command = "./gradlew test" if wrapper else "gradle test"
            analysis.build_command = "./gradlew build" if wrapper else "gradle build"
        else:
            analysis.test_command = "mvn test"
            analysis.build_command = "mvn package"

    if not analysis.project_types:
        nested = _nested_projects(root)
        for _directory, kind in nested:
            if kind not in analysis.project_types:
                analysis.project_types.append(kind)
        if nested:
            listing = ", ".join(f"{directory}/ ({kind})" for directory, kind in nested)
            analysis.notes.append(
                f"no marker at the root — nested projects: {listing}. "
                "Point the tools at the subdirectory (e.g. cwd='backend')."
            )
        else:
            analysis.notes.append(
                "no known project marker found (pyproject.toml, package.json, "
                "Cargo.toml, …) — this may not be a code repository"
            )
    return analysis
