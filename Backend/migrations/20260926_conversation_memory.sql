-- Versioned, durable, non-authoritative semantic memory for long Agent conversations.

CREATE TABLE IF NOT EXISTS geoai_conversation_memory_states (
    memory_id VARCHAR(255) PRIMARY KEY,
    principal_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    summary_version INTEGER NOT NULL,
    covered_from_sequence BIGINT NOT NULL,
    covered_to_sequence BIGINT NOT NULL,
    rolling_summary TEXT NOT NULL,
    active_goal TEXT NOT NULL DEFAULT '',
    user_constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
    explicit_ui_selections JSONB NOT NULL DEFAULT '{}'::jsonb,
    authoritative_runtime_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geoai_conversation_memory_version
        UNIQUE (principal_id, session_id, summary_version)
);

CREATE INDEX IF NOT EXISTS idx_geoai_conversation_memory_latest
    ON geoai_conversation_memory_states (
        principal_id,
        session_id,
        summary_version DESC
    );
