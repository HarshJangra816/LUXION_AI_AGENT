"""Repository intelligence (PRD §17 — Phase 5c).

Luxion must never hand a whole repository to the model. Instead the workspace
is indexed once and retrieved from:

* :mod:`luxion.repository.scanner`   — which files are worth walking
* :mod:`luxion.repository.indexer`   — walk → read → chunk → embed → write
* :mod:`luxion.repository.retrieval` — problem → files → functions → lines

The index lives in the same ``chunks`` table as documents and memories
(``source_type`` ``doc`` / ``code``), so one hybrid search answers all three
and a memory is never mistaken for a file.

Nothing here runs until something asks: ``sync_workspaces`` is called from the
``POST /api/repository/index`` endpoint, from :func:`schedule_index`, or from
the optional ``rag.index_on_start`` boot hook.
"""

from __future__ import annotations

from luxion.repository.indexer import (
    IndexReport,
    count_repo_chunks,
    count_repo_files,
    prune_missing,
    schedule_index,
    sync_workspaces,
)
from luxion.repository.retrieval import (
    FileMatch,
    RepoHit,
    files_relevant_to,
    format_repo_context,
    search_repository,
)
from luxion.repository.scanner import REPO_SOURCE_TYPES, iter_files, normalize_extensions

__all__ = [
    "REPO_SOURCE_TYPES",
    "FileMatch",
    "IndexReport",
    "RepoHit",
    "count_repo_chunks",
    "count_repo_files",
    "files_relevant_to",
    "format_repo_context",
    "iter_files",
    "normalize_extensions",
    "prune_missing",
    "schedule_index",
    "search_repository",
    "sync_workspaces",
]
