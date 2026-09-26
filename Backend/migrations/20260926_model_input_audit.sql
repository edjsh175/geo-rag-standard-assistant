-- Durable audit identity for the exact ModelRequest sent to a provider.
-- Stores hashes and durable references only; raw prompt text is intentionally not persisted.

CREATE TABLE IF NOT EXISTS geoai_model_input_audits (
    audit_id VARCHAR(160) PRIMARY KEY,
    principal_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    call_id VARCHAR(128) NOT NULL,
    attempt INTEGER NOT NULL,
    model_name VARCHAR(255) NULL,
    request_reasoning BOOLEAN NOT NULL DEFAULT FALSE,
    temperature DOUBLE PRECISION NOT NULL,
    timeout_seconds DOUBLE PRECISION NULL,
    response_schema_hash VARCHAR(64) NULL,
    messages_hash VARCHAR(64) NOT NULL,
    messages_section_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_snapshot_id VARCHAR(64) NULL,
    frozen_evidence_snapshot_id VARCHAR(64) NULL,
    action_surface_hash VARCHAR(64) NULL,
    tool_contract_hash VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_geoai_model_input_audits_scoped_call_attempt UNIQUE (
        principal_id, session_id, turn_id, stage, call_id, attempt
    )
);

CREATE INDEX IF NOT EXISTS idx_geoai_model_input_audits_session_turn
    ON geoai_model_input_audits (principal_id, session_id, turn_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_geoai_model_input_audits_messages_hash
    ON geoai_model_input_audits (messages_hash);
