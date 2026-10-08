"""Phase 5c write side: workspace walking + incremental indexing (PRD §17)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from luxion.config.settings import RAGConfig, get_settings
from luxion.database.session import get_session_factory, init_db
from luxion.rag.embeddings import EmbeddingError
from luxion.rag.models import Chunk
from luxion.repository import indexer, scanner
from luxion.repository.scanner import is_excluded, iter_files, normalize_extensions

TREE = {
    "README.md": "# Luxion\n\nA personal desktop agent.\n",
    "src/app.py": "def main() -> None:\n    return None\n",
    "src/util.ts": "export const answer = 42;\n",
    "node_modules/pkg/index.js": "module.exports = 1;\n",
    "dist/bundle.js": "var a = 1;\n",
    "assets/logo.png": "PNG\u0000\u0000binary",
    "notes.log": "not an indexed extension\n",
}


def _build(root: Path, tree: dict[str, str] | None = None) -> Path:
    for name, content in (tree or TREE).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _extensions() -> list[str]:
    return [".md", ".py", ".ts", ".js", ".txt"]


def _exclude() -> list[str]:
    return ["node_modules", "dist", "*.min.js"]


@pytest.fixture()
def session():  # noqa: ANN201
    """Isolated index: the suite shares one database, so clear around each test."""
    init_db()
    db = get_session_factory()()
    _clear_repo(db)
    try:
        yield db
    finally:
        _clear_repo(db)
        db.close()


def _clear_repo(db) -> None:  # noqa: ANN001
    """Delete through ``delete_source`` so the FTS/vector rows go too — a bare
    ``DELETE FROM chunks`` would leave orphan ``chunks_vec`` entries behind and
    the next insert would collide on a reused rowid."""
    from luxion.rag import vector_store

    sources = list(
        db.execute(
            select(Chunk.source).where(Chunk.source_type.in_(scanner.REPO_SOURCE_TYPES)).distinct()
        ).scalars()
    )
    for source in sources:
        vector_store.delete_source(db, source)
    db.commit()


def _cfg(**rag_values):  # noqa: ANN201
    """A settings copy with RAG knobs overridden (never touches the shared one)."""
    settings = get_settings().model_copy(deep=True)
    for key, value in rag_values.items():
        setattr(settings.rag, key, value)
    return settings


# -------------------------------------------------------------------- scanner
def test_normalize_extensions_dedupes_and_prefixes_the_dot() -> None:
    assert normalize_extensions(["PY", ".py", " ", "md", ""]) == (".py", ".md")


def test_is_excluded_matches_plain_names_and_globs() -> None:
    assert is_excluded("node_modules", ["node_modules"]) is True
    assert is_excluded("app.min.js", ["*.min.js"]) is True
    assert is_excluded("app.py", ["node_modules", "*.min.js"]) is False


def test_iter_files_walks_extensions_and_skips_excluded_directories(tmp_path: Path) -> None:
    _build(tmp_path)
    found = {
        str(path.relative_to(tmp_path)).replace("\\", "/")
        for path in iter_files(
            [tmp_path], extensions=_extensions(), exclude=_exclude(), max_bytes=10_000
        )
    }
    # node_modules/ and dist/ are pruned, .log and .png never match the allow-list.
    assert found == {"README.md", "src/app.py", "src/util.ts"}


def test_iter_files_skips_oversized_files(tmp_path: Path) -> None:
    _build(tmp_path, {"small.txt": "ok", "huge.txt": "x" * 5_000})
    found = {
        path.name
        for path in iter_files(
            [tmp_path], extensions=[".txt"], exclude=[], max_files=10, max_bytes=1_000
        )
    }
    assert found == {"small.txt"}


def test_iter_files_stops_at_max_files(tmp_path: Path) -> None:
    tree = {f"file{i:02}.txt": str(i) for i in range(10)}
    _build(tmp_path, tree)
    found = list(iter_files([tmp_path], extensions=[".txt"], exclude=[], max_files=4))
    assert len(found) == 4


def test_iter_files_deduplicates_overlapping_roots(tmp_path: Path) -> None:
    _build(tmp_path, {"a.txt": "a"})
    child = tmp_path / "sub"
    child.mkdir()
    found = list(iter_files([tmp_path, child], extensions=[".txt"], exclude=[], max_files=10))
    assert len(found) == 1


def test_iter_files_ignores_roots_that_do_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    found = list(iter_files([missing], extensions=[".txt"], exclude=[]))
    assert found == []


def test_iter_files_never_yields_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("real", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        import os

        os.symlink(target, link)
    except OSError:  # pragma: no cover - Windows without developer mode
        pytest.skip("symlink creation is not permitted on this machine")
    found = list(iter_files([tmp_path], extensions=[".txt"], exclude=[], max_files=10))
    assert [path.name for path in found] == ["real.txt"]


# -------------------------------------------------------------------- indexer
def test_index_file_writes_markdown_as_a_document(session, tmp_path: Path) -> None:
    _build(tmp_path, {"README.md": "# Title\n\nFirst paragraph.\n\nSecond paragraph.\n"})
    path = tmp_path / "README.md"
    outcome, written = indexer.index_file(session, path)
    assert outcome == indexer.INDEXED
    assert written >= 1

    chunks = (
        session.execute(select(Chunk).where(Chunk.source == str(path)).order_by(Chunk.id))
        .scalars()
        .all()
    )
    assert len(chunks) == written
    assert {chunk.source_type for chunk in chunks} == {"doc"}
    assert {chunk.language for chunk in chunks} == {"markdown"}
    assert all(chunk.start_line >= 1 for chunk in chunks)
    assert all(chunk.embedding is not None for chunk in chunks)


def test_index_file_marks_source_code_as_code(session, tmp_path: Path) -> None:
    content = "def main() -> None:\n    return None\n"
    _build(tmp_path, {"app.py": content})
    path = tmp_path / "app.py"
    indexer.index_file(session, path)
    chunks = (
        session.execute(select(Chunk).where(Chunk.source == str(path)).order_by(Chunk.id))
        .scalars()
        .all()
    )
    assert chunks
    assert {chunk.source_type for chunk in chunks} == {"code"}
    assert {chunk.language for chunk in chunks} == {"python"}
    # 1-based, and the last chunk reaches the final line of the file — the
    # empty line produced by a trailing newline is not a line worth indexing.
    assert min(chunk.start_line for chunk in chunks) == 1
    assert max(chunk.end_line for chunk in chunks) == len(content.splitlines())
    assert all(chunk.text.strip() for chunk in chunks)


def test_index_file_leaves_an_unchanged_file_alone(session, tmp_path: Path) -> None:
    _build(tmp_path, {"notes.md": "Stable content for the hash check."})
    path = tmp_path / "notes.md"

    first, written = indexer.index_file(session, path)
    assert (first, written) == (indexer.INDEXED, 1)

    # Touching the file without changing its content must not re-embed it.
    path.write_text("Stable content for the hash check.", encoding="utf-8")
    second, _ = indexer.index_file(session, path)
    assert second == indexer.UNCHANGED

    path.write_text("Different content entirely.", encoding="utf-8")
    third, rewritten = indexer.index_file(session, path)
    assert (third, rewritten) == (indexer.INDEXED, 1)
    rows = session.execute(select(Chunk).where(Chunk.source == str(path))).scalars().all()
    assert len(rows) == 1, "a changed file replaces its chunks instead of appending"
    assert rows[0].text == "Different content entirely."


def test_index_file_replaces_the_old_chunks_not_appends(session, tmp_path: Path) -> None:
    _build(tmp_path, {"doc.md": "One short paragraph."})
    path = tmp_path / "doc.md"
    indexer.index_file(session, path)
    path.write_text("A much longer replacement with more words in it.", encoding="utf-8")
    _, written = indexer.index_file(session, path)
    rows = session.execute(select(Chunk).where(Chunk.source == str(path))).scalars().all()
    assert len(rows) == written


def test_read_text_rejects_binary_and_oversized_files(tmp_path: Path) -> None:
    binary = tmp_path / "blob.png"
    binary.write_bytes(b"\x89PNG\x00\x00\x00\r")
    huge = tmp_path / "huge.txt"
    huge.write_text("x" * 5_000, encoding="utf-8")
    small = tmp_path / "small.txt"
    small.write_text("hello", encoding="utf-8")

    assert indexer.read_text(binary, max_bytes=10_000) is None
    assert indexer.read_text(huge, max_bytes=1_000) is None
    assert indexer.read_text(small, max_bytes=1_000) == "hello"
    assert indexer.read_text(tmp_path / "missing.txt", max_bytes=1_000) is None


def test_index_file_stays_keyword_only_when_the_model_is_down(
    session, tmp_path: Path, monkeypatch
) -> None:
    def _broken(_settings=None):  # noqa: ANN001, ANN201
        raise EmbeddingError("model unavailable")

    monkeypatch.setattr(indexer, "get_embedding_provider", _broken)
    _build(tmp_path, {"notes.md": "Lambda picks the value at call time."})
    path = tmp_path / "notes.md"
    outcome, written = indexer.index_file(session, path)
    assert (outcome, written) == (indexer.INDEXED, 1)

    chunk = session.execute(select(Chunk).where(Chunk.source == str(path))).scalar_one()
    assert chunk.embedding is None
    assert chunk.text, "an unembedded chunk must still be stored"


def test_index_file_is_skipped_for_a_file_with_nothing_to_chunk(session, tmp_path: Path) -> None:
    _build(tmp_path, {"empty.md": "   \n\n  "})
    path = tmp_path / "empty.md"
    assert indexer.index_file(session, path) == (indexer.SKIPPED, 0)


# ---------------------------------------------------------------------- sync
def test_sync_workspaces_indexes_then_reports_the_next_pass_as_unchanged(
    session, tmp_path: Path
) -> None:
    _build(tmp_path)
    cfg = _cfg(
        index_extensions=_extensions(),
        exclude=_exclude(),
        max_files=100,
        max_file_bytes=10_000,
    )

    first = indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    assert first.scanned == 3
    assert first.indexed == 3
    assert first.unchanged == 0
    assert first.failed == 0
    assert first.files == 3
    assert first.written == first.chunks > 0
    assert first.changed == 3

    second = indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    assert second.indexed == 0
    assert second.unchanged == 3
    assert second.chunks == first.chunks, "an unchanged pass must not add chunks"
    assert second.changed == 0


def test_sync_workspaces_prunes_files_that_disappeared(session, tmp_path: Path) -> None:
    _build(tmp_path, {"keep.md": "stays", "drop.md": "goes away"})
    cfg = _cfg(index_extensions=[".md"], exclude=[], max_files=10)
    root = tmp_path.resolve()
    indexer.sync_workspaces(session, roots=[root], settings=cfg)
    assert indexer.count_repo_files(session) == 2

    (tmp_path / "drop.md").unlink()
    report = indexer.sync_workspaces(session, roots=[root], settings=cfg)
    assert report.removed == 1
    assert indexer.count_repo_files(session) == 1
    remaining = (
        session.execute(select(Chunk.source).where(Chunk.source_type.in_(("doc", "code"))))
        .scalars()
        .all()
    )
    assert [Path(source).name for source in remaining] == ["keep.md"]


def test_sync_workspaces_drops_content_from_a_removed_workspace(session, tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    other = tmp_path / "other"
    other.mkdir()
    _build(approved, {"secret.md": "approved workspace content"})
    cfg = _cfg(index_extensions=[".md"], exclude=[], max_files=10)
    indexer.sync_workspaces(session, roots=[approved.resolve()], settings=cfg)
    assert indexer.count_repo_chunks(session) == 1

    # The workspace is no longer approved: its content must stop being retrievable.
    report = indexer.sync_workspaces(session, roots=[other.resolve()], settings=cfg)
    assert report.removed == 1
    assert indexer.count_repo_chunks(session) == 0


def test_sync_workspaces_is_a_no_op_when_rag_is_disabled(session, tmp_path: Path) -> None:
    _build(tmp_path, {"README.md": "# never indexed"})
    cfg = _cfg(enabled=False, index_extensions=[".md"], exclude=[])
    report = indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    assert report.scanned == 0
    assert report.chunks == 0
    assert indexer.count_repo_chunks(session) == 0


def test_sync_workspaces_counts_a_failure_and_keeps_going(
    session, tmp_path: Path, monkeypatch
) -> None:
    _build(tmp_path, {"good.md": "fine", "bad.md": "blows up"})
    cfg = _cfg(index_extensions=[".md"], exclude=[], max_files=10)
    original = indexer.index_file

    def _explode(session_arg, path, **kwargs):  # noqa: ANN001, ANN201
        if Path(path).name == "bad.md":
            raise RuntimeError("boom")
        return original(session_arg, path, **kwargs)

    monkeypatch.setattr(indexer, "index_file", _explode)
    report = indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    assert report.failed == 1
    assert report.indexed == 1
    assert indexer.count_repo_files(session) == 1


def test_sync_workspaces_bounds_a_pass_with_max_files(session, tmp_path: Path) -> None:
    _build(tmp_path, {f"note{i:02}.md": f"note {i}" for i in range(8)})
    cfg = _cfg(index_extensions=[".md"], exclude=[], max_files=3)
    report = indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    assert report.scanned == 3
    assert indexer.count_repo_files(session) == 3


# ------------------------------------------------------------------- counts
def test_counts_only_cover_repository_chunks(session, tmp_path: Path) -> None:
    from luxion.memory import store as memory_store

    _build(tmp_path, {"README.md": "# indexed"})
    cfg = _cfg(index_extensions=[".md"], exclude=[])
    indexer.sync_workspaces(session, roots=[tmp_path.resolve()], settings=cfg)
    chunks_before = indexer.count_repo_chunks(session)

    memory, _ = memory_store.remember(session, "A memory is not a file")
    try:
        assert indexer.count_repo_files(session) == 1
        assert indexer.count_repo_chunks(session) == chunks_before, (
            "a memory chunk must not count as repository content"
        )
    finally:
        memory_store.forget(session, memory.id)


def test_schedule_index_needs_a_running_loop() -> None:
    assert indexer.schedule_index() is None


def test_schedule_index_is_skipped_when_rag_is_off() -> None:
    cfg = _cfg(enabled=False)
    assert indexer.schedule_index(settings=cfg) is None


def test_settings_expose_the_indexer_knobs() -> None:
    cfg = RAGConfig()
    assert cfg.max_file_bytes >= 1024
    assert cfg.max_files >= 1
    assert cfg.index_on_start is False
    assert cfg.index_extensions, "extensions must never default to empty"
    assert cfg.exclude, "exclude must never default to empty"
