-- Document lifecycle and uploaded-document indexing tables.
-- Apply before enabling upload -> parse -> chunk -> embedding -> search closure.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    file_size BIGINT NOT NULL CHECK (file_size >= 0),
    mime_type VARCHAR(255) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    spatial_metadata JSONB NULL,
    index_status VARCHAR(32) NOT NULL DEFAULT 'queued' CHECK (
        index_status IN ('queued', 'parsing', 'chunking', 'embedding', 'indexed', 'failed', 'deleted')
    ),
    last_error TEXT NULL,
    current_version_id UUID NULL,
    created_by VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL,
    deleted_by VARCHAR(255) NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256_active
    ON documents (sha256)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_documents_status_updated_at
    ON documents (index_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    filename VARCHAR(512) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    file_size BIGINT NOT NULL CHECK (file_size >= 0),
    mime_type VARCHAR(255) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    storage_bucket VARCHAR(255) NOT NULL,
    storage_key VARCHAR(1024) NOT NULL,
    access_url TEXT NULL,
    created_by VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_documents_current_version'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT fk_documents_current_version
            FOREIGN KEY (current_version_id)
            REFERENCES document_versions(id)
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_document_versions_document_id
    ON document_versions (document_id, version_number DESC);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    header_path TEXT NULL,
    page_number INTEGER NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(2048) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (version_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
    ON document_chunks USING hnsw ((CAST(embedding AS halfvec(2048))) halfvec_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS index_jobs (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'retrying', 'cancelled')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 4 CHECK (max_attempts >= 1),
    stage VARCHAR(64) NULL,
    error TEXT NULL,
    requested_by VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_index_jobs_document_id
    ON index_jobs (document_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_index_jobs_status_created_at
    ON index_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS document_events (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_id UUID NULL REFERENCES document_versions(id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES index_jobs(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(255) NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_events_document_id_created_at
    ON document_events (document_id, created_at DESC);
