"""
Fact-Check RQ Worker
====================
Start with:  rq worker factcheck  (or: python worker.py)

Pipeline:
  Tier 1 — fast/cheap check  (stub → replace with GPT-3.5 / embedding)
  Tier 2 — slow/authoritative (stub → replace with GPT-4 + retrieval)

Retry logic is handled inside process_factcheck; RQ itself is not
configured for automatic retries so we control the flow explicitly.
"""

import json
import logging
import time
from rq import Queue, get_current_job
import redis as redis_lib

from app.config import settings
from app.db import get_factcheck, update_factcheck

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Redis ─────────────────────────────────────────────────────────────────────
# Use decode_responses=False so RQ internals (which expect bytes) work correctly.
r = redis_lib.from_url(settings.redis_url, decode_responses=False)

LOCK_PREFIX    = "factcheck:lock:"
PAYLOAD_PREFIX = "factcheck:payload:"
VERDICT_PREFIX = "factcheck:verdict:"   # 24-hour read cache


# ══════════════════════════════════════════════════════════════════════════════
# Stubbed pipeline — replace each function body with real LLM calls
# ══════════════════════════════════════════════════════════════════════════════

def tier1_check(content: str, post_id: str) -> dict:
    """
    Tier 1 — fast heuristic or cheap LLM.
    """
    logger.info("[%s] Tier-1 running...", post_id)
    time.sleep(1)  # simulate LLM latency

    low = content.lower()

    if any(w in low for w in ("false", "fake", "debunked")):
        return {"verdict": "false", "confidence": 0.91, "escalate": False}

    if any(w in low for w in ("uncertain", "maybe", "possibly")):
        # Low confidence → escalate to Tier 2
        return {"verdict": "unverifiable", "confidence": 0.52, "escalate": True}

    return {"verdict": "true", "confidence": 0.84, "escalate": False}


def tier2_check(content: str, post_id: str) -> dict:
    """
    Tier 2 — authoritative check with retrieval augmentation.
    """
    logger.info("[%s] Tier-1 confidence low — escalating to Tier-2...", post_id)
    time.sleep(2)  # simulate retrieval + LLM latency

    return {"verdict": "mixed", "confidence": 0.74}


# ══════════════════════════════════════════════════════════════════════════════
# Main job — called by RQ
# ══════════════════════════════════════════════════════════════════════════════

def process_factcheck(post_id: str) -> dict:
    job = get_current_job()
    logger.info("[%s] Job picked up (job_id=%s)", post_id, job.id if job else "N/A")

    # 1. Idempotency guard
    row = get_factcheck(post_id)
    if not row:
        logger.error("[%s] No DB row found — aborting.", post_id)
        return {"error": "row_not_found"}

    if row["status"] == "done":
        logger.info("[%s] Already done — skipping worker.", post_id)
        return {"skipped": True, "verdict": row["verdict"]}

    if row["status"] == "failed" and (row["attempts"] or 0) >= settings.max_attempts:
        logger.warning("[%s] Max attempts (%d) reached — not re-processing.", post_id, settings.max_attempts)
        return {"skipped": True, "reason": "max_attempts_exceeded"}

    # 2. Retrieve payload
    raw = r.get(f"{PAYLOAD_PREFIX}{post_id}")
    if not raw:
        logger.error("[%s] Payload missing from Redis (expired?).", post_id)
        update_factcheck(post_id, status="failed", error="Payload expired from Redis")
        return {"error": "payload_missing"}

    # raw will be bytes when decode_responses=False; decode to str for json.loads
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")

    payload  = json.loads(raw)
    content  = payload.get("content", "")

    # 3. Mark processing
    new_attempts = (row["attempts"] or 0) + 1
    update_factcheck(post_id, status="processing", attempts=new_attempts)
    logger.info("[%s] Attempt %d/%d", post_id, new_attempts, settings.max_attempts)

    # 4. Run pipeline
    try:
        t1         = tier1_check(content, post_id)
        verdict    = t1["verdict"]
        confidence = t1["confidence"]
        tier_used  = 1

        if t1.get("escalate"):
            t2         = tier2_check(content, post_id)
            verdict    = t2["verdict"]
            confidence = t2["confidence"]
            tier_used  = 2

    except Exception as exc:
        logger.exception("[%s] Pipeline exception on attempt %d: %s", post_id, new_attempts, exc)
        _handle_failure(post_id, new_attempts, str(exc))
        return {"error": str(exc), "attempt": new_attempts}

    # 5. Persist verdict
    update_factcheck(
        post_id,
        status="done",
        verdict=verdict,
        confidence=confidence,
        tier=tier_used,
        error=None,
    )

    # Cache in Redis
    r.setex(
        f"{VERDICT_PREFIX}{post_id}",
        86_400,
        json.dumps({"verdict": verdict, "confidence": confidence, "tier": tier_used}),
    )

    logger.info(
        "[%s] ✓ Done — verdict=%s confidence=%.2f tier=%d",
        post_id, verdict, confidence, tier_used,
    )

    # 6. Release lock
    r.delete(f"{LOCK_PREFIX}{post_id}")

    return {
        "post_id":    post_id,
        "verdict":    verdict,
        "confidence": confidence,
        "tier":       tier_used,
    }


def _handle_failure(post_id: str, attempts: int, error: str) -> None:
    if attempts >= settings.max_attempts:
        logger.error("[%s] All %d attempts exhausted — marking failed.", post_id, attempts)
        update_factcheck(post_id, status="failed", error=error)
        r.delete(f"{LOCK_PREFIX}{post_id}")
    else:
        update_factcheck(post_id, status="pending", error=error)
        retry_q = Queue(settings.worker_queue_name, connection=r)
        retry_q.enqueue(
            process_factcheck,
            post_id,
            job_id=f"fc-{post_id}-r{attempts}",
            job_timeout=120,
        )
        logger.info(
            "[%s] Re-enqueued for retry (attempt %d/%d).",
            post_id, attempts, settings.max_attempts,
        )


# ── Run worker directly: python worker.py ─────────────────────────────────────
if __name__ == "__main__":
    try:
        from rq import Worker
        logger.info("Starting RQ worker on queue '%s'…", settings.worker_queue_name)
        worker = Worker([settings.worker_queue_name], connection=r)
        worker.work(with_scheduler=False)
    except Exception:
        logger.exception("Worker failed to start.")