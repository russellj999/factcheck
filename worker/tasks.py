"""
tasks.py — RQ task functions executed by the worker process.

Each task function is a plain Python callable that RQ deserialises and runs
in a worker subprocess.  All tasks must be importable at module level.

Checkpoint A scope
------------------
`process_verify_job` is the primary task.  In Checkpoint A it:
  1. Updates the verification row to status=processing.
  2. Runs a stub fact-checking loop (placeholder — no external LLM calls yet).
  3. Writes stub results back to Postgres.
  4. Updates status to completed (or failed → DLQ on unrecoverable error).

Subsequent checkpoints will replace the stub with real LLM / RAG calls.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from api.db import queries
from api.logging_config import configure_logging, get_logger, ingest_id_var, verify_job_id_var
from api.config import LOG_LEVEL

# Ensure logging is configured even when imported fresh in a worker subprocess
configure_logging(LOG_LEVEL)
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Checkpoint A constants
# ---------------------------------------------------------------------------
STUB_VERDICT = "UNVERIFIABLE"   # placeholder — no LLM yet
STUB_CONFIDENCE = 0.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


# ---------------------------------------------------------------------------
# Primary task
# ---------------------------------------------------------------------------

def process_verify_job(
    *,
    verify_job_id: str,
    ingest_id: str,
    claims: List[Dict[str, Any]],
    callback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    RQ entrypoint — process a fact-checking job end-to-end.

    Parameters
    ----------
    verify_job_id : str
        UUID of the verification row in Postgres.
    ingest_id : str
        Upstream idempotency key — included in every log line.
    claims : list[dict]
        Serialised claim objects (text, source_url, metadata).
    callback_url : str | None
        Optional webhook to call on completion (stub in Checkpoint A).

    Returns
    -------
    dict  Summary of results written to Postgres.
    """
    # Bind correlation IDs to log context for this job's lifetime
    tok_ingest = ingest_id_var.set(ingest_id)
    tok_job = verify_job_id_var.set(verify_job_id)

    try:
        logger.info(
            "Worker starting job",
            extra={"claim_count": len(claims)},
        )

        # ------------------------------------------------------------------
        # 1. Mark as processing
        # ------------------------------------------------------------------
        queries.update_verification_status(
            verify_job_id=verify_job_id,
            status="processing",
        )

        # ------------------------------------------------------------------
        # 2. Stub fact-checking loop
        #    Replace this section in later checkpoints with real LLM calls.
        # ------------------------------------------------------------------
        results: List[Dict[str, Any]] = []
        for idx, claim in enumerate(claims):
            result = _stub_check_claim(
                claim_index=idx,
                claim_text=claim.get("text", ""),
            )
            results.append(result)
            logger.info(
                "Claim %d processed (stub).",
                idx,
                extra={"verdict": result["verdict"]},
            )

        # ------------------------------------------------------------------
        # 3. Persist results and mark completed
        # ------------------------------------------------------------------
        queries.update_verification_status(
            verify_job_id=verify_job_id,
            status="completed",
            results=results,
        )

        # ------------------------------------------------------------------
        # 4. Optional callback (stub — logs only in Checkpoint A)
        # ------------------------------------------------------------------
        if callback_url:
            _stub_callback(callback_url, verify_job_id, results)

        logger.info("Job completed successfully.")
        return {"verify_job_id": verify_job_id, "claim_count": len(claims), "status": "completed"}

    except Exception as exc:
        logger.exception("Unrecoverable error processing job — moving to DLQ.")
        _handle_failure(
            verify_job_id=verify_job_id,
            ingest_id=ingest_id,
            claims=claims,
            reason=str(exc),
        )
        # Re-raise so RQ marks the job as failed (enables RQ retry if configured)
        raise

    finally:
        ingest_id_var.reset(tok_ingest)
        verify_job_id_var.reset(tok_job)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stub_check_claim(*, claim_index: int, claim_text: str) -> Dict[str, Any]:
    """
    Placeholder fact-check for a single claim.

    Replace with real RAG / LLM logic in Checkpoint B+.
    Introduces a tiny artificial delay to simulate async work.
    """
    time.sleep(0.05)   # simulate latency — remove in production
    return {
        "claim_index": claim_index,
        "claim_text": claim_text,
        "verdict": STUB_VERDICT,
        "confidence": STUB_CONFIDENCE,
        "evidence_urls": [],
        "error": None,
    }


def _stub_callback(callback_url: str, verify_job_id: str, results: List[Dict]) -> None:
    """
    Stub webhook delivery.  In Checkpoint A we only log the intent.
    Checkpoint B will use httpx to POST actual results.
    """
    logger.info(
        "STUB: would POST results to %s for job %s (%d results).",
        callback_url,
        verify_job_id,
        len(results),
    )


def _handle_failure(
    *,
    verify_job_id: str,
    ingest_id: str,
    claims: List[Dict],
    reason: str,
) -> None:
    """Mark job as failed and write a DLQ entry."""
    try:
        queries.update_verification_status(
            verify_job_id=verify_job_id,
            status="failed",
            error_message=reason,
        )
        queries.insert_dlq(
            verify_job_id=verify_job_id,
            ingest_id=ingest_id,
            reason=reason,
            payload={"claims": claims},
        )
    except Exception:
        logger.exception("Failed to write DLQ entry — data may be lost for job %s.", verify_job_id)
