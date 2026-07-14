"""
queries.py — all raw SQL executed by the API layer.

Keeping SQL in one module makes it easy to swap to SQLAlchemy Core later.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from api.db.connection import get_conn
from api.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Verifications
# ---------------------------------------------------------------------------

def insert_verification(
    *,
    ingest_id: str,
    claim_count: int,
    priority: int,
    callback_url: Optional[str],
) -> Dict[str, Any]:
    """
    Insert a new row into `verifications` and return the full row.

    Raises DuplicateIngestId if a row with this ingest_id already exists.
    """
    verify_job_id = uuid4()
    now = datetime.now(tz=timezone.utc)

    sql = """
        INSERT INTO verifications
            (verify_job_id, ingest_id, status, claim_count, priority, callback_url, created_at, updated_at)
        VALUES
            (%(verify_job_id)s, %(ingest_id)s, 'queued', %(claim_count)s,
             %(priority)s, %(callback_url)s, %(now)s, %(now)s)
        RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "verify_job_id": str(verify_job_id),
                "ingest_id": ingest_id,
                "claim_count": claim_count,
                "priority": priority,
                "callback_url": callback_url,
                "now": now,
            })
            row = dict(cur.fetchone())
    logger.info("Inserted verification row.", extra={"verify_job_id": str(verify_job_id)})
    return row


def get_verification_by_ingest_id(ingest_id: str) -> Optional[Dict[str, Any]]:
    """Return an existing verification row for idempotency checks, or None."""
    sql = "SELECT * FROM verifications WHERE ingest_id = %(ingest_id)s LIMIT 1;"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"ingest_id": ingest_id})
            row = cur.fetchone()
    return dict(row) if row else None


def get_verification_by_job_id(verify_job_id: str) -> Optional[Dict[str, Any]]:
    """Return a verification row by verify_job_id, or None if not found."""
    sql = "SELECT * FROM verifications WHERE verify_job_id = %(verify_job_id)s LIMIT 1;"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"verify_job_id": verify_job_id})
            row = cur.fetchone()
    return dict(row) if row else None


def update_verification_status(
    *,
    verify_job_id: str,
    status: str,
    error_message: Optional[str] = None,
    results: Optional[List[Dict]] = None,
) -> None:
    """Update status (and optionally results / error) on a verification row."""
    now = datetime.now(tz=timezone.utc)
    sql = """
        UPDATE verifications
        SET
            status        = %(status)s,
            error_message = %(error_message)s,
            results       = %(results)s,
            updated_at    = %(now)s
        WHERE verify_job_id = %(verify_job_id)s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "status": status,
                "error_message": error_message,
                "results": json.dumps(results) if results else None,
                "now": now,
                "verify_job_id": verify_job_id,
            })
    logger.info("Updated verification status to %s.", status)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def insert_claims(
    *,
    verify_job_id: str,
    claims: List[Dict[str, Any]],
) -> None:
    """Bulk-insert claim rows linked to a verification job."""
    sql = """
        INSERT INTO claims
            (claim_id, verify_job_id, claim_index, claim_text, source_url, metadata)
        VALUES
            (%(claim_id)s, %(verify_job_id)s, %(claim_index)s,
             %(claim_text)s, %(source_url)s, %(metadata)s);
    """
    rows = [
        {
            "claim_id": str(uuid4()),
            "verify_job_id": verify_job_id,
            "claim_index": idx,
            "claim_text": c["text"],
            "source_url": c.get("source_url"),
            "metadata": json.dumps(c.get("metadata") or {}),
        }
        for idx, c in enumerate(claims)
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    logger.info("Inserted %d claim rows.", len(rows))


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------

def insert_dlq(
    *,
    verify_job_id: str,
    ingest_id: str,
    reason: str,
    payload: Optional[Dict] = None,
) -> None:
    """Record a dead-letter entry when a job fails irrecoverably."""
    now = datetime.now(tz=timezone.utc)
    sql = """
        INSERT INTO dlq
            (dlq_id, verify_job_id, ingest_id, reason, payload, created_at)
        VALUES
            (%(dlq_id)s, %(verify_job_id)s, %(ingest_id)s,
             %(reason)s, %(payload)s, %(now)s);
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "dlq_id": str(uuid4()),
                "verify_job_id": verify_job_id,
                "ingest_id": ingest_id,
                "reason": reason,
                "payload": json.dumps(payload or {}),
                "now": now,
            })
    logger.warning("DLQ entry created for verify_job_id=%s.", verify_job_id)
