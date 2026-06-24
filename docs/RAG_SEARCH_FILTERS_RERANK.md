# RAG Search Filters And Rerank Closure

Date: 2026-06-17

## Summary

This change closes the P0 RAG TODOs for retrieval filtering, deterministic reranking, degradation, and search logging. It does not add public endpoints and does not implement the document indexing lifecycle or full spatial API.

## Runtime Behavior

- `search_mode` now affects backend retrieval:
  - `hybrid`: exact standard-code search, keyword search, and vector search when embeddings are available.
  - `keyword`: exact standard-code search plus keyword search; embedding is not requested.
  - `exact`: exact standard-code search only.
  - `semantic` or `vector`: vector search only.
- `use_rerank=false` keeps retriever output order after filtering and truncation.
- `use_rerank=true` applies deterministic local reranking. It does not call an LLM or cross-encoder. It preserves `DocumentResult.similarity` and writes `metadata.rerank_score` plus `metadata.rerank_reasons`.
- If embedding generation fails, `hybrid` search continues with exact and keyword results. Vector search is skipped for that request.

## Filter Semantics

- `metadata_filter.document_type`, `source`, `year`, `region`, `keywords`, and `custom_filters` are matched against whitelisted metadata fields only.
- Unsafe `custom_filters` keys are rejected by returning no match for that candidate.
- `region` supports province/city aliases and local-standard prefixes, for example `重庆市` maps to `DB50`.
- `spatial_filter` supports `intersects`, `within`, `contains`, `near`, `overlaps`, and `disjoint` for document-level GeoJSON geometry in `spatial_info.geometry`.
- If candidate results do not carry document geometry, spatial filtering falls back to `spatial_regions` lookup and maps matched regions to local-standard prefixes.
- Invalid spatial filter geometry returns no results rather than silently ignoring the requested filter.

## Storage

No new environment variables are required.

The existing migration `Backend/migrations/20260617_api_contract_tables.sql` now creates:

- `search_logs`
  - `id BIGSERIAL PRIMARY KEY`
  - `query TEXT NOT NULL`
  - `mode VARCHAR(32) NOT NULL`
  - `top_k INTEGER NOT NULL`
  - `threshold DOUBLE PRECISION NOT NULL`
  - `filters JSONB NULL`
  - `results_count INTEGER NOT NULL`
  - `duration_seconds DOUBLE PRECISION NOT NULL`
  - `used_rerank BOOLEAN NOT NULL`
  - `embedding_available BOOLEAN NULL`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

Indexes:

- `idx_search_logs_created_at`
- `idx_search_logs_mode_created_at`

## Rollback

Application rollback is safe because `search_logs` is write-only observability storage. To remove the table after rolling back the application code:

```sql
DROP INDEX IF EXISTS idx_search_logs_mode_created_at;
DROP INDEX IF EXISTS idx_search_logs_created_at;
DROP TABLE IF EXISTS search_logs;
```

Do not roll back `search_feedback`, `document_overrides`, or `document_reindex_jobs` as part of this RAG-only rollback unless also reverting the earlier API contract governance work.

## Verification

Run backend tests:

```powershell
Backend\.venv\Scripts\python -m pytest Backend\tests -q
```

Run frontend contract/type checks:

```powershell
cd frontend
npm.cmd run lint
```

Verify migration on a clean temporary PostgreSQL database:

```powershell
Backend\.venv\Scripts\python scripts\verify_search_logs_migration.py
```

Run RAG acceptance scenarios without depending on production data:

```powershell
Backend\.venv\Scripts\python scripts\validate_rag_search_scenarios.py
```

The acceptance script covers:

- Standard-code exact query: `DB50/T 1846-2025`
- Keyword query: `滑坡防治 监测`
- Metadata filter by region, year, and document type
- GeoJSON spatial filter that changes the result set
- `use_rerank=false` versus `use_rerank=true`
- Embedding outage fallback for exact/keyword retrieval
- Search-log payload fields for query, mode, filters, result count, duration, rerank, and embedding status
