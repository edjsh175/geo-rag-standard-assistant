-- Persist the ordered per-turn EvidenceLedger activation projection.

CREATE TABLE IF NOT EXISTS geoai_agent_evidence_activations (
    principal_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    turn_id VARCHAR(64) NOT NULL,
    evidence_id VARCHAR(64) NOT NULL,
    ordinal INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (principal_id, session_id, turn_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_geoai_agent_evidence_activations_turn
    ON geoai_agent_evidence_activations (principal_id, session_id, turn_id, ordinal ASC);
