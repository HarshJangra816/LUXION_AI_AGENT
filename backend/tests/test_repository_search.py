"""Phase 5c read side: repository retrieval + the ``search_code`` tool (PRD §17)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from luxion.config.settings import get_settings
from luxion.database.session import get_session_factory, init_db
from luxion.memory import store as memory_store
from luxion.rag import vector_store
from luxion.rag.models import Chunk
from luxion.repository import indexer, retrieval
from luxion.repository.retrieval import (
    FileMatch,
    RepoHit,
    files_relevant_to,
    format_repo_context,
    relative_path,
    search_repository,
)
from luxion.repository.scanner import REPO_SOURCE_TYPES
from luxion.tools.base import Tool, ToolArgumentError, ToolContext, ToolError
from luxion.tools.registry import build_registry
from luxion.tools.router import select_tools

TREE = {
    "backoff.py": (
        "def retry_with_backoff(operation, attempts=5):\n"
        '    """Retry the operation with exponential backoff."""\n'
        "    for attempt in range(attempts):\n"
        "        operation(attempt)\n"
    ),
    "colors.py": 'PRIMARY = "#111827"\nSECONDARY = "#6b7280"\n',
    "README.md": "# Luxion\n\nA personal desktop agent for everyday tasks.\n",
}


@pytest.fixture()
def session():  # noqa: ANN201
    """Isolated index: the suite shares one database, so clear around each test."""
    init_db()
    db = get_session_factory()()
    _clear_repo(db)
    memory_store.clear_memories(db)
    try:
        yield db
    finally:
        _clear_repo(db)
        memory_store.clear_memories(db)
        db.close()


def _clear_repo(db) -> None:  # noqa: ANN001
    """Delete through ``delete_source`` so the FTS/vector rows go too — a bare
    ``DELETE FROM chunks`` would leave orphan ``chunks_vec`` entries behind."""
    sources = list(
        db.execute(
            select(Chunk.source).where(Chunk.source_type.in_(REPO_SOURCE_TYPES)).distinct()
        ).scalars()
    )
    for source in sources:
        vector_store.delete_source(db, source)
    db.commit()


def _workspace(session, tmp_path: Path, tree: dict[str, str] | None = None) -> Path:
    """Write ``tree`` and index it — the setup every retrieval test shares."""
    for name, content in (tree or TREE).items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    root = tmp_path.resolve()
    settings = get_settings().model_copy(deep=True)
    settings.rag.index_extensions = [".md", ".py", ".ts", ".js", ".txt"]
    settings.rag.exclude = []
    settings.rag.max_files = 50
    report = indexer.sync_workspaces(session, roots=[root], settings=settings)
    assert report.indexed >= 1, "the fixture must actually index something"
    return root


def _tool(name: str) -> Tool:
    tool = build_registry(get_settings()).get(name)
    assert tool is not None, f"{name} must be registered"
    return tool


def _run(tool: Tool, **args):  # noqa: ANN001, ANN201
    context = ToolContext(get_settings(), conversation_id=None)
    return asyncio.run(tool.run(args, context))


# ------------------------------------------------------------------ retrieval
def test_search_repository_finds_the_file_that_answers_the_question(
    session, tmp_path: Path
) -> None:
    root = _workspace(session, tmp_path)
    hits = search_repository(session, "retry with backoff", k=3)

    assert hits, "the indexed file must be retrievable"
    assert hits[0].path == str(root / "backoff.py")
    assert hits[0].source_type == "code"
    assert hits[0].language == "python"
    assert hits[0].start_line >= 1
    assert hits[0].end_line >= hits[0].start_line
    assert hits[0].score > 0
    assert "backoff" in hits[0].text


def test_search_repository_returns_empty_for_a_blank_query(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    assert search_repository(session, "   ") == []
    assert search_repository(session, "") == []


def test_search_repository_honours_k(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    everything = search_repository(session, "desktop agent", k=10)
    assert everything, "the fixture corpus must have something to retrieve"
    assert len(search_repository(session, "desktop agent", k=1)) <= 1


def test_search_repository_never_surfaces_a_memory(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    memory_store.remember(session, "Retry with backoff lives in backoff.py")

    hits = search_repository(session, "retry with backoff", k=10)
    assert hits, "the file must still be found"
    assert all(hit.source_type in REPO_SOURCE_TYPES for hit in hits)
    assert all(not hit.path.startswith("memory:") for hit in hits)


def test_search_repository_still_answers_when_the_model_is_down(
    session, tmp_path: Path, monkeypatch
) -> None:
    _workspace(session, tmp_path)
    monkeypatch.setattr(retrieval, "_embed_query", lambda _query: None)

    hits = search_repository(session, "exponential backoff", k=3)
    assert [hit.path for hit in hits if hit.path.endswith("backoff.py")], (
        "an exact identifier must survive the keyword path"
    )


def test_files_relevant_to_groups_hits_under_their_files(session, tmp_path: Path) -> None:
    root = _workspace(session, tmp_path)
    matches = files_relevant_to(session, "retry with backoff", k=8, max_files=3)

    assert matches
    assert matches[0].path == str(root / "backoff.py")
    assert matches[0].score >= matches[-1].score
    assert matches[0].range, "a grouped file must still carry a line range"
    assert matches[0].preview, "a grouped file must explain why it matched"
    assert len({match.path for match in matches}) == len(matches)


def test_files_relevant_to_caps_the_hits_kept_per_file(session, tmp_path: Path) -> None:
    long_file = "\n".join(f"def handler_{index}(): return {index}" for index in range(120))
    _workspace(session, tmp_path, {"handlers.py": long_file})

    matches = files_relevant_to(session, "def handler return", k=20, max_files=5)
    assert matches
    assert len(matches) == 1
    assert len(matches[0].hits) <= retrieval.HITS_PER_FILE


def test_format_repo_context_stays_inside_the_character_budget() -> None:
    hits = [RepoHit("a.py", "code", "python", 1, 2, 0.9, "def a():\n    pass")]
    matches = [FileMatch(path="a.py", source_type="code", language="python", score=0.9, hits=hits)]

    preview = format_repo_context(matches, max_chars=1500)
    assert "a.py" in preview
    assert "1-2" in preview

    tiny = format_repo_context(matches, max_chars=10)
    assert len(tiny) <= 10 or tiny == ""


def test_format_repo_context_ignores_matches_without_hits() -> None:
    empty = FileMatch(path="x.py", source_type="code", language="python", score=0.0)
    assert format_repo_context([empty]) == ""


def test_relative_path_shortens_the_workspace_form(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    inside = root / "src" / "app.py"
    assert Path(relative_path(str(inside), [root])) == Path("src") / "app.py"
    # Outside every root: the absolute path is the honest answer.
    assert relative_path("C:/elsewhere/app.py", [root]).endswith("app.py")


# ----------------------------------------------------------------------- tool
def test_search_code_tool_returns_paths_and_line_ranges(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    result = _run(_tool("search_code"), query="retry with backoff")

    assert "backoff.py" in result.output
    assert ":" in result.output, "the output must address a line range"
    assert result.data["hits"]
    assert result.data["files"]
    assert result.data["hits"][0]["path"].endswith("backoff.py")
    assert result.ok is True


def test_search_code_tool_clamps_its_arguments(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    low = _run(_tool("search_code"), query="desktop agent", k=0).data["hits"]
    assert len(low) <= 1, "k=0 must clamp to the minimum of 1"
    high = _run(_tool("search_code"), query="desktop agent", k=999, files=999).data["hits"]
    assert len(high) <= 20, "k=999 must clamp to the maximum of 20"


def test_search_code_tool_rejects_a_blank_query(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    with pytest.raises(ToolArgumentError):
        _run(_tool("search_code"), query=" ")


def test_search_code_tool_says_when_nothing_matches(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    result = _run(_tool("search_code"), query="flibbertigibbet")
    assert result.data["hits"] == []
    assert "No indexed project files match" in result.output


def test_search_code_tool_is_disabled_when_rag_is_off(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    settings = get_settings().model_copy(deep=True)
    settings.rag.enabled = False

    context = ToolContext(settings, conversation_id=None)
    result = asyncio.run(_tool("search_code").run({"query": "backoff"}, context))
    assert result.data["enabled"] is False
    assert "disabled" in result.output


def test_search_code_tool_is_registered_read_only_and_low_risk() -> None:
    registry = build_registry(get_settings())
    spec = registry.spec("search_code")
    assert spec is not None
    assert spec.risk == "low"
    assert spec.read_only is True
    assert spec.category == "repository"
    assert spec.parameters["required"] == ["query"]

    selected = select_tools("where is the retry backoff handled?", registry, get_settings())
    assert selected[0].name == "search_code", "a 'where is X handled' ask must rank it first"


def test_search_code_tool_never_raises_on_a_missing_index(session) -> None:
    result = _run(_tool("search_code"), query="nothing indexed yet")
    assert result.data["hits"] == []
    assert "index" in result.output.lower()


def test_the_tool_never_returns_memory_content(session, tmp_path: Path) -> None:
    _workspace(session, tmp_path)
    # Same words as the file, so the file *is* retrievable — and the memory is not.
    memory_store.remember(session, "Retry with backoff lives in backoff.py")
    result = _run(_tool("search_code"), query="retry with backoff")

    assert result.data["hits"], "the file must still be the answer"
    assert all(not hit["path"].startswith("memory:") for hit in result.data["hits"])


def test_a_disabled_registry_does_not_expose_the_tool() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.tools.enabled = False
    assert build_registry(settings).get("search_code") is None


def test_tool_error_type_is_the_documented_one() -> None:
    assert issubclass(ToolArgumentError, ToolError)
