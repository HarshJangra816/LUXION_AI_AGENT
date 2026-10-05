"""Embedding providers: normalisation, hash backend, factory/caching."""

import numpy as np
import pytest

from luxion.config.settings import get_settings
from luxion.rag.embeddings import (
    EmbeddingError,
    FastEmbedProvider,
    HashEmbeddingProvider,
    build_provider,
    get_embedding_provider,
    normalize,
    reset_embedding_provider,
)


def test_normalize_unit_length() -> None:
    vector = normalize(np.array([3.0, 4.0], dtype=np.float32))
    assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-6
    assert float(vector[0]) == pytest.approx(0.6, rel=1e-5)


def test_normalize_zero_vector_stays_zero() -> None:
    vector = normalize(np.zeros(8, dtype=np.float32))
    assert np.all(vector == 0)


def test_hash_provider_shape_and_determinism() -> None:
    provider = HashEmbeddingProvider(dim=64)
    assert provider.dim == 64
    assert provider.model == "hash"
    first, second = provider.embed(["hello world"]), provider.embed(["hello world"])
    assert first[0].shape == (64,)
    assert np.allclose(first[0], second[0])
    assert abs(float(np.linalg.norm(first[0])) - 1.0) < 1e-5


def test_hash_provider_is_deterministic_across_instances() -> None:
    text = "the retriever fuses vector and keyword results"
    one = HashEmbeddingProvider(dim=96).embed_query(text)
    two = HashEmbeddingProvider(dim=96).embed_query(text)
    assert np.allclose(one, two)


def test_hash_provider_ranks_shared_words_higher() -> None:
    provider = HashEmbeddingProvider(dim=256)
    chunk = provider.embed_query("the retriever fuses vector and keyword results")
    near = provider.embed_query("retriever keyword results")
    far = provider.embed_query("unrelated words about cooking pasta tonight")
    assert float(chunk @ near) > float(chunk @ far)


def test_hash_provider_handles_empty_text() -> None:
    vector = HashEmbeddingProvider(dim=32).embed_query("")
    assert vector.shape == (32,)
    assert float(np.linalg.norm(vector)) == 0.0


def test_build_provider() -> None:
    assert isinstance(build_provider("hash", "hash"), HashEmbeddingProvider)
    fast = build_provider(
        "fastembed", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert isinstance(fast, FastEmbedProvider)
    # constructing must not download anything (the model loads lazily)
    assert fast.dim == 384
    with pytest.raises(EmbeddingError, match="unknown embedding provider"):
        build_provider("openai", "text-embedding-3-small")


def test_fastembed_dim_lookup_is_catalogued() -> None:
    from luxion.config.settings import EMBEDDING_MODELS, embedding_dim_of

    assert embedding_dim_of(EMBEDDING_MODELS[0].id) == EMBEDDING_MODELS[0].dim
    assert embedding_dim_of("not-a-real/model") is None


def test_provider_caching_roundtrip() -> None:
    settings = get_settings()
    assert settings.rag.provider == "hash"
    provider = get_embedding_provider(settings)
    try:
        assert get_embedding_provider() is provider
    finally:
        reset_embedding_provider()
    assert get_embedding_provider() is not provider
    reset_embedding_provider()
