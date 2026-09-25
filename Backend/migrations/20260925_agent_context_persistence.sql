-- GeoAI Agent context management and event persistence schema
-- Stores Agent sessions, events (event sourcing), evidence items, context snapshots, and pending browser tool executions.

CREATE TABLE IF NOT EXISTS geoai_agent_sessions (
    id VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(64) NOT NULL DEFAULT 'default',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    next_turn_number INTEGER NOT NULL DEFAULT 1,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geoai_agent_sessions_principal_session UNIQUE (principal_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_sessions_principal_session
    ON geoai_agent_sessions (principal_id, session_id);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_sessions_updated_at
    ON geoai_agent_sessions (updated_at DESC);


CREATE TABLE IF NOT EXISTS geoai_agent_events (
    event_id VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(64) NOT NULL DEFAULT '',
    sequence BIGINT NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geoai_agent_events_seq UNIQUE (principal_id, session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_events_session_seq
    ON geoai_agent_events (principal_id, session_id, sequence ASC);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_events_created_at
    ON geoai_agent_events (created_at DESC);


CREATE TABLE IF NOT EXISTS geoai_agent_evidence (
    id VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    evidence_id VARCHAR(64) NOT NULL,
    citation_id VARCHAR(64) NOT NULL,
    first_turn_id VARCHAR(64) NOT NULL,
    chunk_id VARCHAR(255) NOT NULL,
    document_id VARCHAR(255) NULL,
    text TEXT NOT NULL,
    title TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source VARCHAR(64) NOT NULL,
    match_type VARCHAR(64) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geoai_agent_evidence_item UNIQUE (principal_id, session_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_evidence_session_active
    ON geoai_agent_evidence (principal_id, session_id, is_active);


CREATE TABLE IF NOT EXISTS geoai_context_snapshots (
    snapshot_id VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    projection_hash VARCHAR(64) NOT NULL,
    snapshot_payload JSONB NOT NULL,
    token_usage_estimate INTEGER NOT NULL DEFAULT 0,
    source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geoai_context_snapshots_session_turn
    ON geoai_context_snapshots (principal_id, session_id, turn_id);

CREATE INDEX IF NOT EXISTS idx_geoai_context_snapshots_hash
    ON geoai_context_snapshots (projection_hash);


CREATE TABLE IF NOT EXISTS geoai_pending_browser_executions (
    token VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    question TEXT NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    tool_call_id VARCHAR(64) NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    observations JSONB NOT NULL DEFAULT '[]'::jsonb,
    request_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewer_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    thinking BOOLEAN NOT NULL DEFAULT FALSE,
    max_steps INTEGER NOT NULL DEFAULT 6,
    steps_used INTEGER NOT NULL DEFAULT 0,
    max_elapsed_seconds DOUBLE PRECISION NOT NULL DEFAULT 60.0,
    retrieval_constraints JSONB NULL,
    main_model_name VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'awaiting_browser',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_geoai_pending_browser_session_status
    ON geoai_pending_browser_executions (principal_id, session_id, status);

CREATE INDEX IF NOT EXISTS idx_geoai_pending_browser_expires
    ON geoai_pending_browser_executions (expires_at);
