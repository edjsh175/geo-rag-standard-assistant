-- Standard-level spatial applicability facts.
-- Browser active_region remains ephemeral; this table stores only durable standard scope facts.

CREATE TABLE IF NOT EXISTS standard_applicability (
    id BIGSERIAL PRIMARY KEY,
    standard_key TEXT NOT NULL,
    raw_standard_code TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_adcode TEXT,
    scope_geometry geometry(MultiPolygon, 4326),
    scope_text TEXT,
    basis_type TEXT NOT NULL,
    basis_chunk_id TEXT,
    verification_status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_standard_applicability_scope_type
        CHECK (scope_type IN ('nationwide', 'admin_region', 'custom_geometry', 'unresolved')),
    CONSTRAINT ck_standard_applicability_basis_type
        CHECK (basis_type IN ('explicit_scope_clause', 'jurisdiction_default', 'standard_code_derived', 'manual_verified')),
    CONSTRAINT ck_standard_applicability_verification_status
        CHECK (verification_status IN ('verified', 'derived', 'unresolved')),
    CONSTRAINT ck_standard_applicability_scope_payload
        CHECK (
            (scope_type = 'nationwide' AND scope_adcode IS NULL AND scope_geometry IS NULL)
            OR (scope_type = 'admin_region' AND scope_adcode IS NOT NULL AND scope_geometry IS NULL)
            OR (scope_type = 'custom_geometry' AND scope_geometry IS NOT NULL)
            OR (scope_type = 'unresolved' AND scope_adcode IS NULL AND scope_geometry IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_standard_applicability_standard_key
    ON standard_applicability (standard_key);

CREATE INDEX IF NOT EXISTS ix_standard_applicability_scope_adcode
    ON standard_applicability (scope_adcode)
    WHERE scope_adcode IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_standard_applicability_scope_geometry
    ON standard_applicability USING GIST (scope_geometry)
    WHERE scope_geometry IS NOT NULL;

-- Deterministic bootstrap is one fact per standard_key+basis type.  Higher-precedence
-- explicit/manual facts are intentionally allowed to coexist and are resolved later by policy.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standard_applicability_bootstrap_fact
    ON standard_applicability (standard_key, basis_type)
    WHERE basis_type IN ('jurisdiction_default', 'standard_code_derived');

