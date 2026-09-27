-- Add execution_token and active job concurrency constraint for uploaded document indexing.
-- Implements Phase O-02 (Atomic Claim) and O-03 (Single Active Job per Version).

ALTER TABLE index_jobs
    ADD COLUMN IF NOT EXISTS execution_token VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS idx_index_jobs_execution_token
    ON index_jobs (execution_token)
    WHERE execution_token IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_index_jobs_active_version
    ON index_jobs (document_id, version_id)
    WHERE status IN ('queued', 'running', 'retrying');
