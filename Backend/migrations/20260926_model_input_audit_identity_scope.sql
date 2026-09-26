-- Forward repair for installations that already applied the first
-- model-input-audit migration with a global UNIQUE(call_id, attempt).
-- New installations already receive the scoped constraint from
-- 20260926_model_input_audit.sql; this migration is intentionally idempotent.

ALTER TABLE IF EXISTS geoai_model_input_audits
    DROP CONSTRAINT IF EXISTS uq_geoai_model_input_audits_call_attempt;

DO $$
BEGIN
    IF to_regclass('public.geoai_model_input_audits') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM pg_constraint
           WHERE conname = 'uq_geoai_model_input_audits_scoped_call_attempt'
             AND conrelid = 'public.geoai_model_input_audits'::regclass
       ) THEN
        ALTER TABLE geoai_model_input_audits
            ADD CONSTRAINT uq_geoai_model_input_audits_scoped_call_attempt
            UNIQUE (principal_id, session_id, turn_id, stage, call_id, attempt);
    END IF;
END
$$;
