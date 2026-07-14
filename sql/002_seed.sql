-- =============================================================================
-- 002_seed.sql  —  Development seed data for manual testing
--
-- Safe to apply multiple times (uses INSERT ... ON CONFLICT DO NOTHING).
-- Apply:  psql $DATABASE_URL -f sql/002_seed.sql
-- =============================================================================

-- Seed a pre-completed job so GET /verify/{id} works without running a worker
INSERT INTO verifications (
    verify_job_id,
    ingest_id,
    status,
    claim_count,
    priority,
    results,
    created_at,
    updated_at
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'seed-ingest-001',
    'completed',
    2,
    0,
    '[
        {"claim_index": 0, "claim_text": "The Earth is flat.",
         "verdict": "FALSE", "confidence": 0.99, "evidence_urls": [], "error": null},
        {"claim_index": 1, "claim_text": "Water boils at 100°C at sea level.",
         "verdict": "TRUE",  "confidence": 0.99, "evidence_urls": [], "error": null}
    ]'::jsonb,
    NOW() - INTERVAL '1 hour',
    NOW()
) ON CONFLICT (ingest_id) DO NOTHING;

-- Seed a queued job for worker smoke-testing
INSERT INTO verifications (
    verify_job_id,
    ingest_id,
    status,
    claim_count,
    priority,
    created_at,
    updated_at
) VALUES (
    '00000000-0000-0000-0000-000000000002',
    'seed-ingest-002',
    'queued',
    1,
    5,
    NOW(),
    NOW()
) ON CONFLICT (ingest_id) DO NOTHING;

INSERT INTO claims (
    verify_job_id,
    claim_index,
    claim_text
) VALUES (
    '00000000-0000-0000-0000-000000000002',
    0,
    'The moon landing happened in 1969.'
) ON CONFLICT (verify_job_id, claim_index) DO NOTHING;
