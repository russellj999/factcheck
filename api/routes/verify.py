"""
verify.py — FastAPI router for the /verify endpoints.

Endpoints
---------
POST /verify          — Accept a batch of claims; enqueue an RQ job; return 202.
GET  /verify/{id}     — Return current status and results for a job.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status
from redis import Redis
from rq import Queue

from api.config import IDEMPOTENCY_CHECK, REDIS_URL, RQ_JOB_TIMEOUT, RQ_QUEUE_NAME
from api.db import queries
from api.logging_config import get_logger, ingest_id_var, verify_job_id_var
from api.models.schemas import (
    ErrorResponse,
    JobStatus,
    VerifyAccepted,
    VerifyRequest,
    VerifyStatusResponse,
    ClaimResult,
)

router = APIRouter(prefix="/verify", tags=["verify"])
logger = get_logger(__name__)


def _get_rq_queue() -> Queue:
    """Return a connected RQ Queue (lazily created per-request)."""
    redis_conn = Redis.from_url(REDIS_URL)
    return Queue(RQ_QUEUE_NAME, connection=redis_conn, default_timeout=RQ_JOB_TIMEOUT)


# ---------------------------------------------------------------------------
# POST /verify
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VerifyAccepted,
    responses={
        409: {"model": ErrorResponse, "description": "Duplicate ingest_id (idempotency)."},
        422: {"description": "Validation error."},
        503: {"description": "Queue or DB unavailable."},
    },
    summary="Submit claims for fact-checking",
    description=(
        "Accepts a batch of claims identified by `ingest_id`. "
        "Idempotent: re-submitting the same `ingest_id` returns the existing job. "
        "Returns HTTP 202 with the `verify_job_id` for status polling."
    ),
)
async def post_verify(request: Request, body: VerifyRequest) -> Dict[str, Any]:
    # Bind ingest_id to the logging context for this request lifetime
    tok = ingest_id_var.set(body.ingest_id)
    try:
        logger.info(
            "POST /verify received",
            extra={"claim_count": len(body.claims), "priority": body.priority},
        )

        # ------------------------------------------------------------------
        # Idempotency check
        # ------------------------------------------------------------------
        if IDEMPOTENCY_CHECK:
            existing = queries.get_verification_by_ingest_id(body.ingest_id)
            if existing:
                logger.info("Idempotent hit — returning existing job.")
                verify_job_id_var.set(str(existing["verify_job_id"]))
                return VerifyAccepted(
                    verify_job_id=existing["verify_job_id"],
                    ingest_id=existing["ingest_id"],
                    status=JobStatus(existing["status"]),
                    message="Duplicate ingest_id — returning existing job.",
                )

        # ------------------------------------------------------------------
        # Persist the verification row (status=queued)
        # ------------------------------------------------------------------
        try:
            row = queries.insert_verification(
                ingest_id=body.ingest_id,
                claim_count=len(body.claims),
                priority=body.priority,
                callback_url=body.callback_url,
            )
        except Exception as exc:
            logger.exception("DB insert failed.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database error: {exc}",
            ) from exc

        verify_job_id = str(row["verify_job_id"])
        verify_job_id_var.set(verify_job_id)

        # ------------------------------------------------------------------
        # Persist claim rows
        # ------------------------------------------------------------------
        try:
            claims_payload = [c.model_dump() for c in body.claims]
            queries.insert_claims(
                verify_job_id=verify_job_id,
                claims=claims_payload,
            )
        except Exception as exc:
            logger.exception("Failed to insert claim rows.")
            # Non-fatal for the job itself; worker will re-read from DB
            logger.warning("Continuing despite claim insert failure: %s", exc)

        # ------------------------------------------------------------------
        # Enqueue RQ job
        # ------------------------------------------------------------------
        try:
            queue = _get_rq_queue()
            queue_len = len(queue)  # approximate depth before enqueue
            job = queue.enqueue(
                "worker.tasks.process_verify_job",
                kwargs={
                    "verify_job_id": verify_job_id,
                    "ingest_id": body.ingest_id,
                    "claims": claims_payload,
                    "callback_url": body.callback_url,
                },
                job_id=verify_job_id,
                at_front=(body.priority >= 8),
            )
            logger.info("Enqueued RQ job %s (queue depth ~%d).", job.id, queue_len)
        except Exception as exc:
            logger.exception("RQ enqueue failed.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Queue error: {exc}",
            ) from exc

        return VerifyAccepted(
            verify_job_id=uuid.UUID(verify_job_id),
            ingest_id=body.ingest_id,
            status=JobStatus.QUEUED,
            queue_position=queue_len,
        )
    finally:
        ingest_id_var.reset(tok)


# ---------------------------------------------------------------------------
# GET /verify/{verify_job_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{verify_job_id}",
    response_model=VerifyStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found."},
    },
    summary="Get verification job status",
)
async def get_verify_status(verify_job_id: str) -> Dict[str, Any]:
    # Validate UUID format early
    try:
        uuid.UUID(verify_job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="verify_job_id must be a valid UUID.",
        )

    tok = verify_job_id_var.set(verify_job_id)
    try:
        logger.info("GET /verify/%s", verify_job_id)
        row = queries.get_verification_by_job_id(verify_job_id)
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No job found for verify_job_id={verify_job_id}",
            )

        results = None
        if row.get("results"):
            import json as _json

            raw = row["results"]
            if isinstance(raw, str):
                raw = _json.loads(raw)
            results = [ClaimResult(**r) for r in raw] if isinstance(raw, list) else None

        return VerifyStatusResponse(
            verify_job_id=row["verify_job_id"],
            ingest_id=row["ingest_id"],
            status=JobStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            claim_count=row["claim_count"],
            results=results,
            error_message=row.get("error_message"),
        )
    finally:
        verify_job_id_var.reset(tok)
