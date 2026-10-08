"""Workspace walking (PRD §17 ``Repository → Indexer → File analysis``).

Decides *what* is indexable before anything reads it: an allow-listed
extension, nothing under an excluded directory, nothing larger than the
configured cap, and — deliberately — no symlinks, so a link cannot pull
content from outside the workspace the user approved (PRD §42).

Excluded names are matched per path component with shell-style patterns, which
covers both ``node_modules`` (a plain directory name) and ``*.min.js`` (a
filename pattern) with one rule.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

#: Chunk kinds the repository index owns. ``memory`` is never touched here —
#: a sync must not be able to prune Phase 5b entries.
REPO_SOURCE_TYPES: tuple[str, ...] = ("doc", "code")


def normalize_extensions(extensions: Iterable[str]) -> tuple[str, ...]:
    """Lowercase, dot-prefixed suffixes with duplicates removed (``PY`` → ``.py``)."""
    normalized: list[str] = []
    for raw in extensions:
        item = str(raw).strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = f".{item}"
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def is_excluded(name: str, patterns: Iterable[str]) -> bool:
    """True when one path component matches any exclude pattern."""
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def iter_files(
    roots: Iterable[Path | str],
    *,
    extensions: Iterable[str],
    exclude: Iterable[str],
    max_files: int = 5_000,
    max_bytes: int = 512_000,
) -> Iterator[Path]:
    """Every indexable file under ``roots`` in a deterministic order.

    Roots that are missing are skipped silently: a workspace the user removed
    must not stop the remaining ones from indexing. Stops yielding once
    ``max_files`` files have been produced, so a first run on a huge tree is
    bounded rather than unbounded.
    """
    allowed = normalize_extensions(extensions)
    patterns = tuple(str(pattern).strip() for pattern in exclude if str(pattern).strip())
    seen: set[str] = set()
    counted = 0

    for raw_root in roots:
        root = Path(raw_root).expanduser()
        try:
            root = root.resolve()
        except OSError:  # pragma: no cover - unreadable root
            logger.warning("workspace_unreadable path=%s", raw_root)
            continue
        if not root.is_dir():
            logger.info("workspace_missing path=%s", root)
            continue

        for path in _walk(root, patterns=patterns):
            if counted >= max_files:
                logger.info("repository_scan_truncated max_files=%s", max_files)
                return
            if path.suffix.lower() not in allowed:
                continue
            try:
                if path.is_symlink() or path.stat().st_size > max_bytes:
                    continue
            except OSError:  # pragma: no cover - vanished mid-scan
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            counted += 1
            yield path


def _walk(root: Path, *, patterns: tuple[str, ...]) -> Iterator[Path]:
    """Depth-first, sorted — tests and incremental runs both need a fixed order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not is_excluded(name, patterns))
        for name in sorted(filenames):
            if is_excluded(name, patterns):
                continue
            yield Path(dirpath) / name


__all__ = [
    "REPO_SOURCE_TYPES",
    "is_excluded",
    "iter_files",
    "normalize_extensions",
]
