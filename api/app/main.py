import json
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, status
import redis as redis_lib
from rq import Queue

from app.config import settings
from app.db import get_factcheck, insert_factcheck
from app.models import IngestRequest, IngestResponse, FactCheckResponse

# Import the extract router and include it on the app
from app.extract import router as extract_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Async Fact-Check API",
    version="1.0.0",
    description=(
        "Local dev stack: Redis lock + SQLite row + RQ worker. "
        "POST /ingest → 202, then poll GET /fact-check/{post_id}."
    ),
)

# Include the extract router
app.include_router(extract_router)

# ── Redis + RQ (initialized on startup to avoid import-time failures) ──────────
r: Optional[redis_lib.Redis] = None
q: Optional[Queue] = None

LOCK_PREFIX = "factcheck:lock:"
PAYLOAD_PREFIX = "factcheck:payload:"

@app.on_event("startup")
def startup_event():
    """
    Create Redis client and RQ queue at startup so the app can start even if Redis
    is not immediately available during image/container startup.
    """
    global r, q
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        q = Queue(settings.worker_queue_name, connection=r)
        logger.info("Connected to Redis and initialized RQ queue.")
    except Exception:
        # Don't raise here; let endpoints surface connection errors gracefully.
        logger.exception("Failed to initialize Redis/RQ on startup. Will retry on first request.")

@app.on_event("shutdown")
def shutdown_event():
    global r
    try:
        if r:
            r.close()
            logger.info("Closed Redis connection.")
    except Exception:
        logger.exception("Error closing Redis connection on shutdown.")


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    summary="Submit a claim for async fact-checking",
)
def ingest(req: IngestRequest):
    """
    Idempotency contract
    --------------------
    • DB row exists → return current status (no duplicate job).
    • Redis lock held but no DB row → 409 (in-flight duplicate).
    • Neither → acquire lock, insert row, enqueue worker, return 202.
    """
    global r, q
    post_id = req.post_id
    lock_key = f"{LOCK_PREFIX}{post_id}"

    # Ensure Redis/Queue are available
    if r is None or q is None:
        try:
            r = redis_lib.from_url(settings.redis_url, decode_responses=True)
            q = Queue(settings.worker_queue_name, connection=r)
            logger.info("Lazily initialized Redis and RQ.")
        except Exception as exc:
            logger.exception("Redis not available when handling ingest for %s", post_id)
            raise HTTPException(status_code=503, detail="Redis unavailable; try again shortly.")

    # ── 1. DB-level idempotency check (cheapest path) ─────────────────────────
    existing = get_factcheck(post_id)
    if existing:
        logger.info("Duplicate ingest post_id=%s status=%s", post_id, existing["status"])
        return IngestResponse(
            post_id=post_id,
            status=existing["status"],
            message="Already received — returning current status.",
        )

    # ── 2. Acquire Redis distributed lock (SET NX EX) ─────────────────────────
    try:
        acquired = r.set(lock_key, "1", nx=True, ex=settings.redis_lock_ttl)
    except Exception:
        logger.exception("Redis error while acquiring lock for %s", post_id)
        raise HTTPException(status_code=503, detail="Redis error; try again shortly.")

    if not acquired:
        logger.warning("Lock held for post_id=%s", post_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A processing lock is already held for '{post_id}'. "
                "Retry in a few seconds."
            ),
        )

    # ── 3. Stash full payload in Redis (worker reads it) ──────────────────────
    # Choose best available text field and cap size to avoid huge payloads
    content = (
        req.original_text
        or req.translated_text
        or req.content
        or ""
    )
    max_payload_chars = getattr(settings, "max_payload_chars", 20000)
    content = content[:max_payload_chars]

    payload = {
        "post_id":    post_id,
        "content":    content,
        "source_url": req.source_url,
        "ingest_id":  req.ingest_id,
        "metadata": {
            "detected_language": req.detected_language,
            "post_type":         req.post_type,
            "content_type":      req.content_type,
            "timestamp":         req.timestamp,
            "source":            req.source,
        },
    }

    # Use a separate TTL for payloads if configured, otherwise fall back to lock TTL
    payload_ttl = getattr(settings, "redis_payload_ttl", settings.redis_lock_ttl)
    try:
        r.setex(f"{PAYLOAD_PREFIX}{post_id}", payload_ttl, json.dumps(payload))
    except Exception:
        # If we can't stash the payload, release the lock and fail fast
        try:
            r.delete(lock_key)
        except Exception:
            logger.exception("Failed to delete lock after payload stash failure for %s", post_id)
        logger.exception("Failed to stash payload for %s", post_id)
        raise HTTPException(status_code=503, detail="Redis error; try again shortly.")

    # ── 4. Insert DB row ───────────────────────────────────────────────────────
    try:
        insert_factcheck(post_id)
    except Exception:
        try:
            r.delete(lock_key)
        except Exception:
            logger.exception("Failed to delete lock for post_id=%s after DB insert error", post_id)
        logger.exception("DB insert failed post_id=%s", post_id)
        raise HTTPException(status_code=500, detail="Database error — please retry.")

    # ── 5. Enqueue RQ job ──────────────────────────────────────────────────────
    try:
        # import inside function to avoid circular imports at module import time
        from app.worker import process_factcheck
        job = q.enqueue(
            process_factcheck,
            post_id,
            job_id=f"fc-{post_id}",
            job_timeout=getattr(settings, "worker_job_timeout", 120),
        )
        logger.info("Enqueued job=%s for post_id=%s", job.id, post_id)
    except Exception:
        # If enqueue fails, clean up DB/lock as appropriate (DB row exists; lock should be removed)
        try:
            r.delete(lock_key)
        except Exception:
            logger.exception("Failed to delete lock after enqueue failure for %s", post_id)
        logger.exception("Failed to enqueue job for %s", post_id)
        raise HTTPException(status_code=500, detail="Queue error — please retry.")

    return IngestResponse(
        post_id=post_id,
        status="pending",
        message="Accepted. Poll GET /fact-check/{post_id} for results.",
    )


@app.get(
    "/fact-check/{post_id}",
    response_model=FactCheckResponse,
    summary="Poll for fact-check status and verdict",
)
def poll(post_id: str):
    """Return the current status (and verdict once done) for a post_id."""
    row = get_factcheck(post_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No fact-check found for post_id='{post_id}'.",
        )
    return FactCheckResponse(**row)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}