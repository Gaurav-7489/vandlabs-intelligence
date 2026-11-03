# ADR-0005: Keyword search first; pgvector deferred
**Status:** accepted. Postgres full-text (`websearch_to_tsquery`, GIN) is implemented and tenant-scoped. pgvector is **not** installed in the verified environment and no
embedding pipeline exists; semantic/hybrid search is a Phase 2 item. No claim of semantic retrieval is made anywhere in the product.
