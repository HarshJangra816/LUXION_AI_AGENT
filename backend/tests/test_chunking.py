"""Chunking: prose windows, code boundaries, suffix dispatch (PRD §16)."""

from luxion.rag.chunking import (
    CODE_KIND,
    PROSE_KIND,
    _is_boundary,
    chunk_code,
    chunk_file,
    chunk_prose,
    kind_of,
    language_of,
)

_PROSE = (
    "# Retrieval\n\n"
    "The retriever fuses vector and keyword results.\n\n"
    "Luxion uses fastembed for embeddings in Phase 5.\n"
)

_CODE = "\n".join(
    [
        "import os",
        "",
        "def alpha():",
        "    return 1",
        "",
        "def beta():",
        "    return 2",
        "",
        "class Gamma:",
        "    pass",
    ]
)


def test_language_of_and_kind_of() -> None:
    assert language_of("README.md") == "markdown"
    assert language_of("main.py") == "python"
    assert language_of("schema.sql") == "sql"
    assert language_of("docker-compose.yml") == "yaml"
    assert language_of("LICENSE") == ""
    assert kind_of("markdown") == PROSE_KIND
    assert kind_of("text") == PROSE_KIND
    assert kind_of("python") == CODE_KIND
    assert kind_of("") == CODE_KIND


def test_prose_chunks_are_ordered_and_cover_the_text() -> None:
    drafts = chunk_prose(_PROSE, max_chars=60, overlap=20, language="markdown")
    assert drafts, "expected at least one prose chunk"
    assert all(d.kind == PROSE_KIND for d in drafts)
    assert all(d.text.strip() for d in drafts)
    assert drafts[0].start_line == 1
    assert drafts[-1].end_line == 5
    previous = 0
    for draft in drafts:
        assert draft.start_line > previous
        assert draft.end_line >= draft.start_line
        previous = draft.start_line
    joined = " ".join(d.text for d in drafts)
    assert "fuses vector" in joined
    assert "fastembed" in joined


def test_oversized_paragraph_is_split() -> None:
    paragraph = " ".join(f"word{i}" for i in range(200))
    max_chars, overlap = 80, 10
    drafts = chunk_prose(paragraph, max_chars=max_chars, overlap=overlap, language="text")
    assert len(drafts) > 1
    # the tail overlap may extend a chunk past the budget, nothing else may
    assert all(len(d.text) <= max_chars + overlap + 2 for d in drafts)


def test_empty_prose_returns_nothing() -> None:
    assert chunk_prose("   \n\n  ") == []


def test_code_chunks_prefer_definitions() -> None:
    drafts = chunk_code(_CODE, language="python", max_chars=60, line_overlap=1)
    assert len(drafts) >= 2
    assert all(d.kind == CODE_KIND for d in drafts)
    assert drafts[0].start_line == 1
    assert drafts[-1].end_line == len(_CODE.split("\n"))
    assert any(d.text.startswith(("def ", "class ")) for d in drafts)


def test_code_line_numbers_are_sane() -> None:
    lines = [f"line_{index} = {index}" for index in range(60)]
    drafts = chunk_code("\n".join(lines), language="python", max_chars=60, line_overlap=0)
    assert len(drafts) > 1
    for draft in drafts:
        assert 1 <= draft.start_line <= draft.end_line <= 60
        first = lines[draft.start_line - 1]
        assert first in draft.text


def test_line_boundaries() -> None:
    assert _is_boundary("def parse(text):")
    assert _is_boundary("class Store:")
    assert _is_boundary("export const flag = 1")
    assert _is_boundary("# a comment")
    assert _is_boundary("-- sql comment")
    assert _is_boundary("main() {")
    assert not _is_boundary("    value = compute()")
    assert not _is_boundary("x = 1")
    assert _is_boundary("")  # a blank line is always a safe split point
    assert _is_boundary("   ")


def test_chunk_file_dispatches_on_suffix() -> None:
    prose = chunk_file("notes.md", _PROSE, max_chars=100)
    assert prose and prose[0].language == "markdown" and prose[0].kind == PROSE_KIND

    code = chunk_file("app.py", _CODE, max_chars=100)
    assert code and code[0].language == "python" and code[0].kind == CODE_KIND

    sql = chunk_file("queries.sql", "SELECT 1;\nSELECT 2;\n", max_chars=100)
    assert sql and sql[0].language == "sql" and sql[0].kind == CODE_KIND

    rst = chunk_file("guide.rst", "Title\n=====\n\nBody text.\n", max_chars=100)
    assert rst and rst[0].language == "text" and rst[0].kind == PROSE_KIND

    assert chunk_file("empty.md", "") == []
