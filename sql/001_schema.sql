-- =============================================================================
-- 001_schema.sql  —  Tier-2 Fact-Check LLM  —  Checkpoint A baseline schema
--
-- Tables
--   verifications   : one row per verify job (primary audit trail)
--   claims          : one row per claim within a job
--   dlq             : dead-letter queue for irrecoverably failed jobs
--
-- Run order:  this file only (idempotent via IF NOT EXISTS / CREATE OR REPLACE)
-- Apply:      psql $DATABASE_URL -f sql/001_schema.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- ENUM: job status
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
        CREATE TYPE job_status AS ENUM (
            'queued',
            'processing',
            'completed',
            'failed',
            'dlq'
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- verifications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verifications (
    verify_job_id   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    ingest_id       TEXT            NOT NULL,
    status          job_status      NOT NULL DEFAULT 'queued',
    claim_count     INTEGER         NOT NULL CHECK (claim_count > 0),
    priority        SMALLINT        NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 10),
    callback_url    TEXT,
    results         JSONB,
    error_message   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Enforce idempotency: only one active job per ingest_id
CREATE UNIQUE INDEX IF NOT EXISTS uix_verifications_ingest_id
    ON verifications (ingest_id);

-- Speed up status-based polling / worker queries
CREATE INDEX IF NOT EXISTS ix_verifications_status
    ON verifications (status)
    WHERE status IN ('queued', 'processing');

CREATE INDEX IF NOT EXISTS ix_verifications_created_at
    ON verifications (created_at DESC);

COMMENT ON TABLE  verifications               IS 'One row per fact-checking job submitted via POST /verify.';
COMMENT ON COLUMN verifications.verify_job_id IS 'Primary key; also used as the RQ job ID.';
COMMENT ON COLUMN verifications.ingest_id     IS 'Upstream idempotency key from the ingest pipeline.';
COMMENT ON COLUMN verifications.results       IS 'JSONB array of ClaimResult objects written by the worker.';

-- ---------------------------------------------------------------------------
-- claims  (placeholder — Checkpoint A writes rows; Checkpoint B enriches them)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
    claim_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    verify_job_id   UUID        NOT NULL REFERENCES verifications (verify_job_id) ON DELETE CASCADE,
    claim_index     INTEGER     NOT NULL CHECK (claim_index >= 0),
    claim_text      TEXT        NOT NULL,
    source_url      TEXT,
    metadata        JSONB       DEFAULT '{}',

    -- Verdict fields — populated by the worker in later checkpoints
    verdict         TEXT,                       -- TRUE | FALSE | UNVERIFIABLE
    confidence      NUMERIC(4,3),               -- 0.000 – 1.000
    evidence_urls   JSONB,                      -- array of URL strings
    error           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (verify_job_id, claim_index)
);

CREATE INDEX IF NOT EXISTS ix_claims_verify_job_id
    ON claims (verify_job_id);

COMMENT ON TABLE  claims             IS 'Individual claims belonging to a verification job.';
COMMENT ON COLUMN claims.claim_index IS 'Zero-based position within the submitted claims array.';
COMMENT ON COLUMN claims.verdict     IS 'Fact-check verdict — populated by worker (Checkpoint B+).';

-- ---------------------------------------------------------------------------
-- dlq  — dead-letter queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dlq (
    dlq_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    verify_job_id   UUID        NOT NULL,       -- no FK — parent may be corrupt
    ingest_id       TEXT        NOT NULL,
    reason          TEXT        NOT NULL,
    payload         JSONB       DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_dlq_verify_job_id
    ON dlq (verify_job_id);

CREATE INDEX IF NOT EXISTS ix_dlq_created_at
    ON dlq (created_at DESC);

COMMENT ON TABLE dlq IS 'Dead-letter entries for jobs that failed irrecoverably after all retries.';

-- ---------------------------------------------------------------------------
-- updated_at trigger (shared function)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_verifications_updated_at'
    ) THEN
        CREATE TRIGGER trg_verifications_updated_at
        BEFORE UPDATE ON verifications
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_claims_updated_at'
    ) THEN
        CREATE TRIGGER trg_claims_updated_at
        BEFORE UPDATE ON claims
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END
$$;
