"""Literal / regex code search (PRD §34 "Searching code", Phase 8).

The exact-string counterpart to the semantic ``search_code`` tool: when the
model already knows the symbol (``def flush_stream``) or the error text it
needs to fix (``AttributeError: 'NoneType'``), a grep-style walk over the
workspace answers precisely — no index required, works on files the vector
index has never seen.

Pure stdlib (``re``), no ripgrep dependency. Binary files, huge files and
ignored directories (``.git``, ``node_modules``, …) are skipped; the result
is clipped to a hit cap so a broad pattern cannot flood the context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luxion.coding.analyzer import SKIP_DIRS

#: Files larger than this are treated as binary and skipped.
MAX_FILE_BYTES = 1024 * 1024
#: Hard cap on returned hits.
MAX_HITS = 200
#: Default cap a caller asks for.
DEFAULT_HITS = 50

#: Suffixes never searched (binaries, archives, media, fonts).
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".7z",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".wav",
        ".webm",
        ".class",
        ".jar",
        ".pyc",
        ".pyo",
    }
)


@dataclass
class GrepHit:
    """One matching line."""

    path: str
    line: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "text": self.text}


def _compile(pattern: str, *, regex: bool, ignore_case: bool) -> re.Pattern[str]:
    flags = re.IGNORECASE if ignore_case else 0
    try:
        return re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc


def grep_files(
    root: Path,
    pattern: str,
    *,
    regex: bool = False,
    ignore_case: bool = False,
    include: str | None = None,
    max_hits: int = DEFAULT_HITS,
) -> list[GrepHit]:
    """Search text files under ``root`` for ``pattern``.

    ``include`` is a glob matched against the file *name* (``*.py``,
    ``*.ts``, ``test_*.py``). ``max_hits`` is clamped to ``MAX_HITS``.
    Raises :class:`ValueError` for an invalid regex.
    """
    compiled = _compile(pattern, regex=regex, ignore_case=ignore_case)
    limit = max(1, min(int(max_hits), MAX_HITS))
    hits: list[GrepHit] = []
    include_pattern = re.compile(_glob_to_regex(include)) if include else None

    stack = [Path(root)]
    while stack and len(hits) < limit:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if len(hits) >= limit:
                break
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
                continue
            if entry.suffix.lower() in BINARY_SUFFIXES:
                continue
            if include_pattern and not include_pattern.match(entry.name):
                continue
            hits.extend(_search_file(entry, compiled, limit - len(hits)))
    return hits


def _glob_to_regex(glob: str) -> str:
    r"""``*.py`` → ``.*\.py`` anchored at both ends (fnmatch-like, name only)."""
    pieces = ["^"]
    for char in glob:
        if char == "*":
            pieces.append(".*")
        elif char == "?":
            pieces.append(".")
        else:
            pieces.append(re.escape(char))
    pieces.append("$")
    return "".join(pieces)


def _search_file(path: Path, compiled: re.Pattern[str], remaining: int) -> list[GrepHit]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in raw[:8192]:
        return []  # binary sniff
    text = raw.decode("utf-8", errors="replace")
    hits: list[GrepHit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if compiled.search(line):
            hits.append(GrepHit(path=str(path), line=number, text=line.strip()[:300]))
            if len(hits) >= remaining:
                break
    return hits
