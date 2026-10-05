"""Embedding providers (PRD §16 "Chunking → Embedding → Vector Database").

Two implementations behind one small protocol:

``fastembed``
    The shipped default: an offline ONNX model through ``onnxruntime``. No
    server, no API key, downloaded once into the HuggingFace cache.

``hash``
    A deterministic, dependency-free stand-in (sha1-seeded bag of tokens).
    It knows nothing about semantics, but it exercises the whole index /
    search / context pipeline without a network or a 200 MB download — so
    tests and CI never touch the real model.

Both return **L2-normalised float32** vectors: for unit vectors cosine
similarity and euclidean distance rank identically, which lets the sqlite-vec
table keep its default (fast) metric while ``min_score`` still means "cosine".

Vectors are never built here for long documents in one call — callers batch.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from luxion.config.settings import (
    DEFAULT_EMBEDDING_MODEL,
    embedding_dim_of,
    get_settings,
)

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """The model could not be loaded or a batch could not be embedded."""


def normalize(vector: np.ndarray) -> np.ndarray:
    """L2-normalise to float32 (a zero vector is left alone, not NaN)."""
    vec = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm == 0.0 or not np.isfinite(norm):
        return vec
    return vec / norm


@runtime_checkable
class EmbeddingProvider(Protocol):
    """What :mod:`luxion.rag.vector_store` needs from an embedding backend."""

    @property
    def model(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedProvider:
    """Offline ONNX embeddings via :mod:`fastembed` (lazy, thread-safe)."""

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL, *, dim: int | None = None) -> None:
        self._model = model
        self._dim = int(dim or embedding_dim_of(model) or 0)
        self._impl: object | None = None
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    def _load(self) -> object:
        if self._impl is not None:
            return self._impl
        with self._lock:
            if self._impl is None:
                try:
                    from fastembed import TextEmbedding  # noqa: PLC0415 - optional dep

                    logger.info("embedding_model_loading model=%s", self._model)
                    self._impl = TextEmbedding(model_name=self._model)
                except Exception as exc:  # noqa: BLE001 - surfaced as EmbeddingError
                    raise EmbeddingError(
                        f"could not load embedding model '{self._model}': {exc}"
                    ) from exc
        return self._impl

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        impl = self._load()
        try:
            raw = list(impl.embed(list(texts)))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - model/runtime failures
            raise EmbeddingError(f"embedding failed for '{self._model}': {exc}") from exc
        vectors = [normalize(np.asarray(item, dtype=np.float32)) for item in raw]
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"model '{self._model}' returned {len(vectors)} vectors for {len(texts)} texts"
            )
        if vectors and self._dim != vectors[0].shape[0]:
            self._dim = int(vectors[0].shape[0])
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        embedded = self.embed([text])
        if not embedded:
            raise EmbeddingError("nothing to embed")
        return embedded[0]


class HashEmbeddingProvider:
    """Deterministic sha1 bag-of-tokens vectors (offline, no model).

    Semantically weak by design — it exists so the retrieval pipeline can be
    tested and demoed with ``LUXION_RAG__PROVIDER=hash``. Shared tokens still
    collide into nearby directions, so a query containing a chunk's words
    ranks that chunk first.
    """

    def __init__(self, model: str = "hash", *, dim: int = 384) -> None:
        self._model = model
        self._dim = max(8, int(dim))

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        for token in text.casefold().split():
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            # sha1 is 20 bytes -> 5 full 4-byte blocks (20 - 1 = 19 inclusive)
            for block in range(0, 18, 4):
                index = int.from_bytes(digest[block : block + 2], "little") % self._dim
                sign = 1.0 if digest[block + 2] % 2 else -1.0
                vec[index] += sign
        return normalize(vec)

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)


def build_provider(provider: str, model: str, *, dim: int | None = None) -> EmbeddingProvider:
    """Construct a provider by id (``fastembed`` | ``hash``)."""
    if provider == "hash":
        return HashEmbeddingProvider(model="hash", dim=dim or 384)
    if provider != "fastembed":
        raise EmbeddingError(f"unknown embedding provider '{provider}'")
    return FastEmbedProvider(model, dim=dim)


_provider: EmbeddingProvider | None = None
_provider_key: tuple[str, str, int] | None = None


def get_embedding_provider(settings=None) -> EmbeddingProvider:
    """Cached provider for the current settings (rebuilt when they change)."""
    global _provider, _provider_key
    resolved = settings or get_settings()
    key = (resolved.rag.provider, resolved.rag.embedding_model, resolved.embedding_dim)
    if _provider is None or _provider_key != key:
        _provider = build_provider(
            resolved.rag.provider,
            resolved.rag.embedding_model,
            dim=resolved.embedding_dim,
        )
        _provider_key = key
    return _provider


def reset_embedding_provider() -> None:
    """Drop the cached provider (tests, and after a Settings → Memory save)."""
    global _provider, _provider_key
    _provider = None
    _provider_key = None


__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "FastEmbedProvider",
    "HashEmbeddingProvider",
    "build_provider",
    "get_embedding_provider",
    "normalize",
    "reset_embedding_provider",
]
