# Fact-Check LLM — Tier-2 Verify API — Checkpoint A

> **Status:** Checkpoint A — skeleton complete. No external LLM calls yet.  
> All fact-check verdicts are stubs (`UNVERIFIABLE / 0.0`). Real inference arrives in Checkpoint B.

---

## Table of Contents
1. [Architecture](#architecture)
2. [Directory Layout](#directory-layout)
3. [Prerequisites](#prerequisites)
4. [Quick Start (Docker Compose)](#quick-start-docker-compose)
5. [Local Development (venv)](#local-development-venv)
6. [Environment Variables](#environment-variables)
7. [API Reference](#api-reference)
8. [Running the Test Suite](#running-the-test-suite)
9. [Smoke-Test Script](#smoke-test-script)
10. [Database](#database)
11. [Logging](#logging)
12. [Idempotency](#idempotency)
13. [Checkpoint A Runbook](#checkpoint-a-runbook)
14. [Troubleshooting](#troubleshooting)

---

## Architecture

```
[Upstream Ingest]
       │  POST /verify  (HTTP)
       ▼
┌─────────────────┐       enqueue       ┌──────────────────┐
│  FastAPI  (api) │ ──────────────────► │  RQ Worker       │
│  POST /verify   │                     │  worker/tasks.py │
│  GET  /verify/  │                     └────────┬─────────┘
└────────┬────────┘                              │ update status / results
         │                                       │
         │  read/write                           │
         ▼                                       ▼
┌─────────────────────────────────────────────────────────┐
│                   PostgreSQL                            │
│   verifications │ claims │ dlq                         │
└─────────────────────────────────────────────────────────┘
         ▲                  ▲
         │  job metadata    │  job queue
         └──────────────────┘
                   Redis
```

**Flow:**
1. Upstream ingest calls `POST /verify` with an `ingest_id` (idempotency key) and a list of claims.  
2. The API inserts a `verifications` row (`status=queued`), inserts individual `claims` rows, and enqueues an RQ job using `verify_job_id` as the job ID.  
3. The RQ worker picks up the job, updates status to `processing`, runs stub fact-checking, writes results to Postgres, then updates status to `completed`.  
4. Failed jobs write a DLQ entry and are marked `failed`.  
5. Callers poll `GET /verify/{verify_job_id}` for status and results.

---

## Directory Layout

```
tier2/
├── api/
│   ├── main.py                  # FastAPI app, lifespan, router mount
│   ├── config.py                # All env-var config in one place
│   ├── logging_config.py        # JSON logging + ingest_id/verify_job_id context vars
│   ├── models/
│   │   └── schemas.py           # Pydantic request/response models
│   ├── routes/
│   │   └── verify.py            # POST /verify  +  GET /verify/{id}
│   └── db/
│       ├── connection.py        # psycopg2 ThreadedConnectionPool
│       └── queries.py           # All SQL (insert, select, update)
├── worker/
│   ├── tasks.py                 # RQ task: process_verify_job()
│   └── run_worker.py            # Worker entry point
├── sql/
│   ├── 001_schema.sql           # DDL: verifications, claims, dlq, triggers
│   └── 002_seed.sql             # Dev seed data
├── samples/
│   ├── post_verify_single.json  # Single-claim POST body
│   ├── post_verify_batch.json   # 3-claim POST body with callback_url
│   └── post_verify_idempotent.json  # Duplicate ingest_id sample
├── scripts/
│   └── test_checkpoint_a.sh    # End-to-end smoke-test (curl + jq)
├── tests/
│   ├── conftest.py              # Shared pytest fixtures (all I/O mocked)
│   ├── test_verify_endpoint.py  # 15 unit tests for POST/GET /verify
│   └── test_worker_tasks.py     # 9 unit tests for worker task logic
├── Dockerfile.api               # API + db-init image
├── Dockerfile.worker            # Worker image
├── docker-compose.yml           # All services wired together
├── .env.example                 # Copy to .env before running locally
├── requirements.txt             # Python dependencies
└── pytest.ini                   # Pytest configuration
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker Desktop | ≥ 4.x | With Compose v2 (`docker compose`) |
| Python | ≥ 3.12 | For local venv dev only |
| curl + jq | any | For the smoke-test script |

---

## Quick Start (Docker Compose)

```powershell
# 1. Enter the project directory
cd C:\Russ\Projects\Fact-Check-LLM\tier2

# 2. Copy and (optionally) edit environment variables
copy .env.example .env

# 3. Build images and start all services
docker compose up --build

# Expected startup order:
#   postgres  → healthy
#   redis     → healthy
#   db-init   → applies 001_schema.sql + 002_seed.sql, then exits
#   api       → listening on http://localhost:8000
#   worker    → waiting for RQ jobs
```

**Verify everything is up:**
```powershell
# Health check
curl http://localhost:8000/healthz

# Expected: {"status":"ok","version":"0.1.0-checkpoint-a"}
```

**Stop all services:**
```powershell
docker compose down          # keep postgres volume
docker compose down -v       # also wipe postgres data
```

---

## Local Development (venv)

Run API and worker directly on your machine — requires Postgres and Redis already running (e.g. via `docker compose up postgres redis`).

```powershell
cd C:\Russ\Projects\Fact-Check-LLM\tier2

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit env vars (point to localhost Postgres/Redis)
copy .env.example .env

# Apply the schema to a local Postgres instance
$env:DATABASE_URL="postgresql://factcheck:factcheck@localhost:5432/factcheck"
psql $env:DATABASE_URL -f sql/001_schema.sql
psql $env:DATABASE_URL -f sql/002_seed.sql

# Start the API (auto-reload for development)
python -m api.main

# In a second terminal — start the worker
.venv\Scripts\activate
python -m worker.run_worker
```

---

## Environment Variables

All variables have safe defaults for local Docker development. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Postgres hostname |
| `POSTGRES_PORT` | `5432` | Postgres port |
| `POSTGRES_DB` | `factcheck` | Database name |
| `POSTGRES_USER` | `factcheck` | Database user |
| `POSTGRES_PASSWORD` | `factcheck` | Database password |
| `DATABASE_URL` | _(derived)_ | Full DSN — overrides individual vars |
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_URL` | _(derived)_ | Full Redis URL — overrides individual vars |
| `RQ_QUEUE_NAME` | `verify` | RQ queue name |
| `RQ_JOB_TIMEOUT` | `300` | Max seconds per job |
| `API_HOST` | `0.0.0.0` | uvicorn bind host |
| `API_PORT` | `8000` | uvicorn bind port |
| `LOG_LEVEL` | `INFO` | Python log level |
| `IDEMPOTENCY_CHECK` | `true` | Enable/disable duplicate ingest_id guard |

---

## API Reference

Interactive docs at **http://localhost:8000/docs** (Swagger UI) and **/redoc**.

### `POST /verify`

Submit a batch of claims for asynchronous fact-checking.

**Request body:**
```json
{
  "ingest_id": "ingest-2026-abc123",
  "claims": [
    {
      "text": "The claim to fact-check.",
      "source_url": "https://example.com/article",
      "metadata": {"article_id": "art-001"}
    }
  ],
  "priority": 0,
  "callback_url": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `ingest_id` | string | ✅ | Idempotency key from upstream ingest |
| `claims` | array | ✅ | 1+ claim objects |
| `claims[].text` | string | ✅ | The claim text (1–4096 chars) |
| `claims[].source_url` | string | ❌ | Origin URL |
| `claims[].metadata` | object | ❌ | Arbitrary key-value pairs |
| `priority` | int 0–10 | ❌ | Default 0; ≥8 → front of queue |
| `callback_url` | string | ❌ | Webhook (stub in Checkpoint A) |

**Response — HTTP 202:**
```json
{
  "verify_job_id": "550e8400-e29b-41d4-a716-446655440000",
  "ingest_id": "ingest-2026-abc123",
  "status": "queued",
  "queue_position": 0,
  "message": "Job accepted and queued for processing."
}
```

---

### `GET /verify/{verify_job_id}`

Poll job status and retrieve results.

**Response — HTTP 200:**
```json
{
  "verify_job_id": "550e8400-e29b-41d4-a716-446655440000",
  "ingest_id": "ingest-2026-abc123",
  "status": "completed",
  "created_at": "2026-07-13T20:00:00Z",
  "updated_at": "2026-07-13T20:00:05Z",
  "claim_count": 1,
  "results": [
    {
      "claim_index": 0,
      "claim_text": "The claim to fact-check.",
      "verdict": "UNVERIFIABLE",
      "confidence": 0.0,
      "evidence_urls": [],
      "error": null
    }
  ],
  "error_message": null
}
```

**Status values:** `queued` → `processing` → `completed` | `failed` | `dlq`

---

### `GET /healthz`

Liveness probe — returns `{"status":"ok"}` with HTTP 200.

---

## Running the Test Suite

Unit tests run entirely in-process with all I/O mocked — **no Docker or network required**.

```powershell
cd C:\Russ\Projects\Fact-Check-LLM\tier2

# Activate venv and install deps (if not already done)
.venv\Scripts\activate
pip install -r requirements.txt

# Run all tests with verbose output
pytest -v

# Run only endpoint tests
pytest -v tests/test_verify_endpoint.py

# Run only worker tests
pytest -v tests/test_worker_tasks.py

# Run with coverage report
pip install pytest-cov
pytest --cov=api --cov=worker --cov-report=term-missing
```

**Expected output (Checkpoint A — 24 tests):**
```
tests/test_verify_endpoint.py::TestPostVerify::test_returns_202            PASSED
tests/test_verify_endpoint.py::TestPostVerify::test_response_body_schema   PASSED
tests/test_verify_endpoint.py::TestPostVerify::test_rq_enqueue_called_once PASSED
tests/test_verify_endpoint.py::TestPostVerify::test_db_insert_called_once  PASSED
...
tests/test_worker_tasks.py::TestProcessVerifyJobSuccess::test_sets_processing_before_completed PASSED
...
========================= 24 passed in X.XXs =========================
```

---

## Smoke-Test Script

Requires all Docker services running (`docker compose up --build`), plus `curl` and `jq`.

```powershell
# From Git Bash, WSL, or any bash shell:
cd /c/Russ/Projects/Fact-Check-LLM/tier2
chmod +x scripts/test_checkpoint_a.sh
./scripts/test_checkpoint_a.sh
```

**Tests performed:**
1. `GET /healthz` → `status=ok`
2. `POST /verify` single claim → HTTP 202, verify_job_id returned
3. `POST /verify` same ingest_id → same verify_job_id (idempotency)
4. `GET /verify/{id}` → 200, fields present
5. Poll until worker marks job `completed`
6. `POST /verify` batch (3 claims) → 202
7. `GET /verify/<nonexistent>` → 404
8. `GET /verify/not-a-uuid` → 422
9. Seeded job from `002_seed.sql` → status `completed`

---

## Database

### Applying the schema manually

```powershell
# Inside Docker
docker compose exec postgres psql -U factcheck -d factcheck -f /docker-entrypoint-initdb.d/001_schema.sql

# Or from host (requires psql installed)
psql postgresql://factcheck:factcheck@localhost:5432/factcheck -f sql/001_schema.sql
psql postgresql://factcheck:factcheck@localhost:5432/factcheck -f sql/002_seed.sql
```

### Inspecting data

```powershell
docker compose exec postgres psql -U factcheck -d factcheck

-- Recent jobs
SELECT verify_job_id, ingest_id, status, claim_count, created_at
FROM verifications ORDER BY created_at DESC LIMIT 10;

-- Claims for a job
SELECT * FROM claims WHERE verify_job_id = '<your-uuid>';

-- DLQ entries
SELECT * FROM dlq ORDER BY created_at DESC;
```

---

## Logging

All log output is **structured JSON**, one object per line, written to stdout.  
Every log line includes `ingest_id` and `verify_job_id` when set.

```json
{
  "ts": "2026-07-13T20:00:01.234567+00:00",
  "level": "INFO",
  "logger": "api.routes.verify",
  "message": "POST /verify received",
  "ingest_id": "ingest-2026-abc123",
  "verify_job_id": null
}
```

**Tail logs in Docker:**
```powershell
docker compose logs -f api
docker compose logs -f worker
```

---

## Idempotency

The API enforces idempotency on `ingest_id` at the database level (unique index) and at the application level (early exit before DB write).

| Scenario | Behaviour |
|---|---|
| First submission | New `verifications` row + RQ job created |
| Duplicate `ingest_id` (job queued/processing) | Existing row returned, no new job enqueued |
| Duplicate `ingest_id` (job completed) | Existing completed results returned immediately |
| `IDEMPOTENCY_CHECK=false` | Check disabled — useful for load testing |

---

## Checkpoint A Runbook

Complete end-to-end validation sequence:

```powershell
# ── Step 1: Start services ────────────────────────────────────────────────
cd C:\Russ\Projects\Fact-Check-LLM\tier2
docker compose up --build -d
docker compose ps            # all 4 services should be "running" or "healthy"

# ── Step 2: Health check ──────────────────────────────────────────────────
curl http://localhost:8000/healthz
# {"status":"ok","version":"0.1.0-checkpoint-a"}

# ── Step 3: Submit a job ──────────────────────────────────────────────────
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d @samples/post_verify_single.json

# Save the verify_job_id from the response
set VERIFY_JOB_ID=<paste-uuid-here>

# ── Step 4: Poll for completion ───────────────────────────────────────────
curl http://localhost:8000/verify/%VERIFY_JOB_ID%
# status should move: queued → processing → completed

# ── Step 5: Verify DB row ─────────────────────────────────────────────────
docker compose exec postgres psql -U factcheck -d factcheck \
  -c "SELECT verify_job_id, ingest_id, status, claim_count FROM verifications ORDER BY created_at DESC LIMIT 5;"

# ── Step 6: Run unit tests ────────────────────────────────────────────────
.venv\Scripts\activate
pytest -v
# 24 passed

# ── Step 7: Run smoke tests ───────────────────────────────────────────────
# (Git Bash or WSL)
./scripts/test_checkpoint_a.sh
# Results: X passed / 0 failed

# ── Step 8: Check worker logs ─────────────────────────────────────────────
docker compose logs worker --tail=50
# Should show JSON logs with ingest_id + verify_job_id on every line

# ── Step 9: Tear down ─────────────────────────────────────────────────────
docker compose down
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `db-init` container exits with error | Postgres not ready | Increase healthcheck retries in compose or wait longer |
| `api` returns 503 on POST /verify | Redis unreachable | Check `docker compose ps redis`; confirm REDIS_URL |
| Worker never picks up jobs | Wrong queue name | Ensure `RQ_QUEUE_NAME` matches in both api and worker envs |
| `UniqueViolation` in Postgres | Duplicate ingest_id race condition | Idempotency check runs before insert; safe to retry |
| `psycopg2.OperationalError` | Wrong DB credentials or host | Double-check DATABASE_URL in .env |
| Tests import errors | PYTHONPATH not set | Run pytest from `tier2/` root; `pytest.ini` sets `testpaths=tests` |
| Port 8000 already in use | Another process on 8000 | Set `API_PORT_EXTERNAL=8001` in .env |
| Port 5432 already in use | Local Postgres running | Set `POSTGRES_PORT_EXTERNAL=5433` in .env |

---

*Checkpoint A complete. Checkpoint B will add real LLM inference calls inside `worker/tasks.py::_stub_check_claim()`.*
