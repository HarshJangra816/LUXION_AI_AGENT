-- Static DDL for the RAG index (PRD §16 "Vector Database → Semantic Search").
-- Executed by luxion.rag.vector_store.ensure_index_tables() at startup.
--
-- The vec0 virtual table is created from Python because its vector width comes
-- from the configured embedding model (and is rebuilt when that changes).
-- `chunk_id UNINDEXED` keeps the row id of `chunks` in the full-text index so
-- both searches can be fused without a join.

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    chunk_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
