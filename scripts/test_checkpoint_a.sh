#!/usr/bin/env bash
# =============================================================================
# test_checkpoint_a.sh — Smoke-test script for Tier-2 Checkpoint A
#
# Prerequisites:
#   - docker compose up --build (all services healthy)
#   - curl, jq installed on your machine
#
# Usage:
#   chmod +x scripts/test_checkpoint_a.sh
#   ./scripts/test_checkpoint_a.sh
#
# Exit codes:  0 = all checks passed   1 = one or more checks failed
# =============================================================================

set -euo pipefail

BASE_URL="${API_BASE_URL:-http://localhost:8000}"
PASS=0
FAIL=0
VERIFY_JOB_ID=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
green() { printf "\e[32m✔  %s\e[0m\n" "$*"; }
red()   { printf "\e[31m✘  %s\e[0m\n" "$*"; }
blue()  { printf "\e[34m── %s\e[0m\n" "$*"; }

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    green "$label (got: $actual)"
    PASS=$((PASS + 1))
  else
    red "$label (expected: $expected, got: $actual)"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_empty() {
  local label="$1" actual="$2"
  if [ -n "$actual" ] && [ "$actual" != "null" ]; then
    green "$label (got: $actual)"
    PASS=$((PASS + 1))
  else
    red "$label (was empty or null)"
    FAIL=$((FAIL + 1))
  fi
}

# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------
blue "TEST 1: GET /healthz"
HEALTH=$(curl -sf "${BASE_URL}/healthz" || echo '{}')
STATUS=$(echo "$HEALTH" | jq -r '.status // "missing"')
assert_eq "Healthz status=ok" "ok" "$STATUS"

# ---------------------------------------------------------------------------
# 2. POST /verify — single claim (should return 202)
# ---------------------------------------------------------------------------
blue "TEST 2: POST /verify — single claim"
INGEST_ID="test-$(date +%s)-single"

RESPONSE=$(curl -sf -X POST "${BASE_URL}/verify" \
  -H "Content-Type: application/json" \
  -d "{
    \"ingest_id\": \"${INGEST_ID}\",
    \"claims\": [{
      \"text\": \"The Great Wall of China is visible from space.\",
      \"source_url\": \"https://example.com/test\",
      \"metadata\": {}
    }],
    \"priority\": 0,
    \"callback_url\": null
  }" || echo '{}')

echo "  Response: $RESPONSE"
HTTP_STATUS_MSG=$(echo "$RESPONSE" | jq -r '.status // "missing"')
VERIFY_JOB_ID=$(echo "$RESPONSE" | jq -r '.verify_job_id // ""')
RETURNED_INGEST=$(echo "$RESPONSE" | jq -r '.ingest_id // ""')

assert_eq   "POST /verify returns status=queued"    "queued"     "$HTTP_STATUS_MSG"
assert_not_empty "POST /verify returns verify_job_id"              "$VERIFY_JOB_ID"
assert_eq   "POST /verify echoes ingest_id"         "$INGEST_ID" "$RETURNED_INGEST"

# ---------------------------------------------------------------------------
# 3. POST /verify — idempotency (same ingest_id, expect same verify_job_id)
# ---------------------------------------------------------------------------
blue "TEST 3: POST /verify — idempotency check (same ingest_id)"
sleep 1   # small delay to ensure DB write is committed

RESPONSE2=$(curl -sf -X POST "${BASE_URL}/verify" \
  -H "Content-Type: application/json" \
  -d "{
    \"ingest_id\": \"${INGEST_ID}\",
    \"claims\": [{
      \"text\": \"The Great Wall of China is visible from space.\",
      \"source_url\": \"https://example.com/test\",
      \"metadata\": {}
    }],
    \"priority\": 0,
    \"callback_url\": null
  }" || echo '{}')

VERIFY_JOB_ID2=$(echo "$RESPONSE2" | jq -r '.verify_job_id // ""')
assert_eq "Idempotency: same verify_job_id returned" "$VERIFY_JOB_ID" "$VERIFY_JOB_ID2"

# ---------------------------------------------------------------------------
# 4. GET /verify/{verify_job_id}
# ---------------------------------------------------------------------------
blue "TEST 4: GET /verify/${VERIFY_JOB_ID}"
sleep 2   # give worker time to pick up the job

GET_RESPONSE=$(curl -sf "${BASE_URL}/verify/${VERIFY_JOB_ID}" || echo '{}')
echo "  Response: $GET_RESPONSE"
GET_JOB_ID=$(echo "$GET_RESPONSE" | jq -r '.verify_job_id // ""')
GET_INGEST=$(echo "$GET_RESPONSE" | jq -r '.ingest_id // ""')
GET_STATUS=$(echo "$GET_RESPONSE" | jq -r '.status // ""')

assert_not_empty "GET /verify returns verify_job_id"    "$GET_JOB_ID"
assert_eq        "GET /verify echoes ingest_id"         "$INGEST_ID" "$GET_INGEST"
assert_not_empty "GET /verify returns a status"         "$GET_STATUS"

# ---------------------------------------------------------------------------
# 5. GET /verify/{verify_job_id} — status should be completed (worker ran)
# ---------------------------------------------------------------------------
blue "TEST 5: Wait for worker to complete job"
for i in {1..15}; do
  POLL=$(curl -sf "${BASE_URL}/verify/${VERIFY_JOB_ID}" | jq -r '.status')
  if [ "$POLL" = "completed" ] || [ "$POLL" = "failed" ]; then
    break
  fi
  echo "  Polling ($i/15): status=$POLL — waiting 2s..."
  sleep 2
done

FINAL_STATUS=$(curl -sf "${BASE_URL}/verify/${VERIFY_JOB_ID}" | jq -r '.status')
assert_eq "Worker completed job" "completed" "$FINAL_STATUS"

# ---------------------------------------------------------------------------
# 6. POST /verify — batch (3 claims)
# ---------------------------------------------------------------------------
blue "TEST 6: POST /verify — batch 3 claims"
BATCH_INGEST="test-$(date +%s)-batch"

BATCH_RESP=$(curl -sf -X POST "${BASE_URL}/verify" \
  -H "Content-Type: application/json" \
  -d @samples/post_verify_batch.json 2>/dev/null || \
  curl -sf -X POST "${BASE_URL}/verify" \
  -H "Content-Type: application/json" \
  -d "{
    \"ingest_id\": \"${BATCH_INGEST}\",
    \"claims\": [
      {\"text\": \"Claim A\"},
      {\"text\": \"Claim B\"},
      {\"text\": \"Claim C\"}
    ],
    \"priority\": 2
  }" || echo '{}')

BATCH_STATUS=$(echo "$BATCH_RESP" | jq -r '.status // "missing"')
assert_eq "Batch POST returns queued" "queued" "$BATCH_STATUS"

# ---------------------------------------------------------------------------
# 7. GET /verify/{bad-id} — 404
# ---------------------------------------------------------------------------
blue "TEST 7: GET /verify/<nonexistent> — expect 404"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE_URL}/verify/00000000-dead-beef-0000-000000000000")
assert_eq "GET nonexistent job returns 404" "404" "$HTTP_CODE"

# ---------------------------------------------------------------------------
# 8. GET /verify/bad-uuid — 422
# ---------------------------------------------------------------------------
blue "TEST 8: GET /verify/not-a-uuid — expect 422"
HTTP_CODE422=$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE_URL}/verify/not-a-uuid-at-all")
assert_eq "GET bad UUID format returns 422" "422" "$HTTP_CODE422"

# ---------------------------------------------------------------------------
# 9. Seeded completed job (from 002_seed.sql)
# ---------------------------------------------------------------------------
blue "TEST 9: GET seeded completed job"
SEED_RESP=$(curl -sf \
  "${BASE_URL}/verify/00000000-0000-0000-0000-000000000001" || echo '{}')
SEED_STATUS=$(echo "$SEED_RESP" | jq -r '.status // "missing"')
assert_eq "Seeded job status=completed" "completed" "$SEED_STATUS"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=============================="
echo "  Results: ${PASS} passed  /  ${FAIL} failed"
echo "=============================="

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
