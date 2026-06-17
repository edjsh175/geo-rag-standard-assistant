-- API contract governance tables.
-- Apply explicitly before enabling feedback, document overrides, soft delete,
-- and reindex queue endpoints in production.

CREATE TABLE IF NOT EXISTS search_feedback (
    id UUID PRIMARY KEY,
    query TEXT NOT NULL,
    result_id TEXT NOT NULL,
    feedback_type VARCHAR(32) NOT NULL CHECK (
        feedback_type IN ('relevant', 'irrelevant', 'helpful', 'not_helpful')
    ),
    comment TEXT NULL,
    rating INTEGER NULL CHECK (rating BETWEEN 1 AND 5),
    user_role VARCHAR(64) NULL,
    username VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_feedback_result_id
    ON search_feedback (result_id);

CREATE INDEX IF NOT EXISTS idx_search_feedback_created_at
    ON search_feedback (created_at DESC);

CREATE TABLE IF NOT EXISTS document_overrides (
    doc_id TEXT PRIMARY KEY,
    metadata_override JSONB NOT NULL DEFAULT '{}'::jsonb,
    spatial_metadata_override JSONB NULL,
    deleted_at TIMESTAMPTZ NULL,
    deleted_by VARCHAR(255) NULL,
    updated_by VARCHAR(255) NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_overrides_deleted_at
    ON document_overrides (deleted_at)
    WHERE deleted_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_reindex_jobs (
    id UUID PRIMARY KEY,
    doc_id TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    requested_by VARCHAR(255) NULL,
    error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_document_reindex_jobs_doc_id
    ON document_reindex_jobs (doc_id);

CREATE INDEX IF NOT EXISTS idx_document_reindex_jobs_status_created_at
    ON document_reindex_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS search_logs (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    mode VARCHAR(32) NOT NULL,
    top_k INTEGER NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    filters JSONB NULL,
    results_count INTEGER NOT NULL,
    duration_seconds DOUBLE PRECISION NOT NULL,
    used_rerank BOOLEAN NOT NULL,
    embedding_available BOOLEAN NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_logs_created_at
    ON search_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_search_logs_mode_created_at
    ON search_logs (mode, created_at DESC);
