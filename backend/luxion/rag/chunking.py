"""Chunking (PRD §16 "Source → Chunking", §17 "Code chunking").

Two strategies, dispatched by file type:

``prose``  paragraphs/sentences for ``.md`` / ``.txt`` / ``.rst``, sized in
           characters with a tail overlap so a thought split across the window
           is still retrievable.
``code``   line-bounded for source files and ``.sql``: a chunk never cuts
           mid-line, prefers to break on a top-level boundary (blank line, a
           statement ending in ``;``, a ``def``/``class``/``export`` opener) and
           carries a few context lines into the next chunk.

Both report the **1-based line range** they cover, because PRD §17 asks
retrieval to answer with "relevant files → functions → lines".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Chunk kinds stored in ``chunks.source_type``.
PROSE_KIND = "doc"
CODE_KIND = "code"

#: Suffix → language id (drives both the chunker and the code fence shown in UI).
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".rst": "text",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".css": "css",
    ".html": "html",
    ".vue": "vue",
}

#: Languages treated as prose (everything else uses the line-bounded chunker).
PROSE_LANGUAGES = frozenset({"markdown", "text"})

_SENTENCE = re.compile(r"[^.!?।\n]+[.!?।]*\s*")
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
_LINE_BOUNDARY = re.compile(
    r"^\s*(?:"
    r"(?:def|class|async\s+def|function|fn|func|pub\s+fn|export|const|let|"
    r"interface|type|impl|struct|enum|module|package|import|from|#|##|\-\-|"
    r"/\*\*|<!--)"
    r"|[A-Za-z_][\w.]*\s*\("
    r"|[^\s].*[{;:]$"
    r")"
)


@dataclass(slots=True)
class ChunkDraft:
    """A chunk before it is embedded and persisted."""

    text: str
    start_line: int
    end_line: int
    kind: str
    language: str = ""


def language_of(path: str | Path) -> str:
    """Language id for a file suffix (``""`` when unknown)."""
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "")


def kind_of(language: str) -> str:
    """``doc`` for prose languages, ``code`` for everything else."""
    return PROSE_KIND if language in PROSE_LANGUAGES else CODE_KIND


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    """1-based line number for a character offset."""
    import bisect  # noqa: PLC0415 - tiny helper, keeps the import local

    return bisect.bisect_right(starts, offset)


def _hard_split(
    piece: str, offset: int, starts: list[int], max_chars: int
) -> list[tuple[str, int]]:
    """Window a piece that is longer than the whole budget."""
    out: list[tuple[str, int]] = []
    cursor = 0
    while cursor < len(piece):
        window = piece[cursor : cursor + max_chars]
        out.append((window, offset + cursor))
        cursor += max_chars
    return out


def _split_oversized(
    piece: str, offset: int, starts: list[int], max_chars: int
) -> list[tuple[str, int]]:
    """Sentence-split a paragraph that does not fit in one chunk."""
    pieces: list[tuple[str, int]] = []
    cursor = 0
    for match in _SENTENCE.finditer(piece):
        sentence = match.group()
        if not sentence.strip():
            continue
        if len(sentence) > max_chars:
            if cursor < match.start():
                pieces.append((piece[cursor : match.start()], offset + cursor))
            pieces.extend(_hard_split(sentence, offset + match.start(), starts, max_chars))
            cursor = match.end()
            continue
        pieces.append((sentence, offset + match.start()))
        cursor = match.end()
    if cursor < len(piece) and piece[cursor:].strip():
        pieces.append((piece[cursor:], offset + cursor))
    return pieces or _hard_split(piece, offset, starts, max_chars)


def chunk_prose(
    text: str,
    *,
    max_chars: int = 800,
    overlap: int = 120,
    language: str = "text",
) -> list[ChunkDraft]:
    """Paragraph/sentence windows with a character tail overlap."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    starts = _line_starts(text)

    # (piece, offset) - paragraphs first, then any that are too big on their own.
    units: list[tuple[str, int]] = []
    cursor = 0
    for match in _PARAGRAPH_SPLIT.finditer(text):
        para = text[cursor : match.start()]
        if para.strip():
            units.append((para, cursor))
        cursor = match.end()
    tail = text[cursor:]
    if tail.strip():
        units.append((tail, cursor))

    sized: list[tuple[str, int]] = []
    for piece, offset in units:
        if len(piece) > max_chars:
            sized.extend(_split_oversized(piece, offset, starts, max_chars))
        else:
            sized.append((piece, offset))

    drafts: list[ChunkDraft] = []
    buffer = ""
    buffer_offset = 0
    for piece, offset in sized:
        candidate = piece if not buffer else f"{buffer}\n\n{piece}"
        if buffer and len(candidate) > max_chars:
            drafts.append(_prose_draft(buffer, buffer_offset, starts, language))
            tail = buffer[-overlap:] if overlap else ""
            buffer = f"{tail}\n\n{piece}" if tail else piece
            buffer_offset = offset - len(tail) if tail else offset
        else:
            if not buffer:
                buffer_offset = offset
            buffer = candidate
    if buffer.strip():
        drafts.append(_prose_draft(buffer, buffer_offset, starts, language))
    return drafts


def _prose_draft(text: str, offset: int, starts: list[int], language: str) -> ChunkDraft:
    end_offset = offset + len(text)
    return ChunkDraft(
        text=text.strip(),
        start_line=_line_of(starts, offset),
        end_line=_line_of(starts, max(offset, end_offset - 1)),
        kind=PROSE_KIND,
        language=language,
    )


def _is_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(_LINE_BOUNDARY.match(stripped))


def chunk_code(
    text: str,
    *,
    language: str = "",
    max_chars: int = 800,
    line_overlap: int = 4,
) -> list[ChunkDraft]:
    """Line-bounded chunks that prefer top-level boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not any(line.strip() for line in lines):
        return []

    drafts: list[ChunkDraft] = []
    start = 0
    total = len(lines)
    while start < total:
        size = 0
        end = start
        while end < total:
            added = len(lines[end]) + 1
            if size + added > max_chars and end > start:
                break
            size += added
            end += 1
        cut = total if end >= total else _safe_cut(lines, start, end)
        block = lines[start:cut]
        while block and not block[-1].strip() and cut > start + 1:
            cut -= 1
            block = lines[start:cut]
        if not block:
            cut = min(start + 1, total)
            block = lines[start:cut]
        # A run of blank lines (the trailing newline of most files is one)
        # yields no text to retrieve — and a blank chunk embeds to a zero
        # vector, which the vector index scores *above* real matches.
        if any(line.strip() for line in block):
            drafts.append(
                ChunkDraft(
                    text="\n".join(block).strip("\n"),
                    start_line=start + 1,
                    end_line=cut,
                    kind=CODE_KIND,
                    language=language,
                )
            )
        if cut >= total:
            break
        next_start = max(cut - line_overlap, start + 1)
        start = next_start
    return drafts


def _safe_cut(lines: list[str], start: int, end: int) -> int:
    """Latest boundary inside the buffer (never the first line: no progress)."""
    floor = max(start + 1, end - max(1, (end - start) // 2))
    for index in range(end - 1, floor - 1, -1):
        if _is_boundary(lines[index]):
            return index + 1
    return end


def chunk_file(
    path: str | Path,
    text: str,
    *,
    max_chars: int = 800,
    overlap: int = 120,
    line_overlap: int = 4,
) -> list[ChunkDraft]:
    """Chunk a file with the strategy its suffix calls for."""
    language = language_of(path)
    if language in PROSE_LANGUAGES:
        return chunk_prose(text, max_chars=max_chars, overlap=overlap, language=language)
    return chunk_code(text, language=language, max_chars=max_chars, line_overlap=line_overlap)


__all__ = [
    "CODE_KIND",
    "ChunkDraft",
    "PROSE_KIND",
    "chunk_code",
    "chunk_file",
    "chunk_prose",
    "kind_of",
    "language_of",
]
