"""
conftest.py — shared pytest fixtures for Tier-2 Checkpoint A tests.

Fixtures
--------
app_client     : TestClient with a fully patched DB and Redis.
mock_db_row    : Factory for a fake verification DB row dict.
mock_rq_queue  : Patched RQ Queue that records enqueued jobs without Redis.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_verification_row(
    ingest_id: str = "ingest-test-001",
    status: str = "queued",
    claim_count: int = 1,
    verify_job_id: str | None = None,
) -> Dict[str, Any]:
    """Return a dict that mimics a psycopg2 RealDictCursor row."""
    vid = verify_job_id or str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    return {
        "verify_job_id": uuid.UUID(vid),
        "ingest_id": ingest_id,
        "status": status,
        "claim_count": claim_count,
        "priority": 0,
        "callback_url": None,
        "results": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_rq_queue() -> MagicMock:
    """A MagicMock that stands in for rq.Queue."""
    q = MagicMock()
    q.__len__ = MagicMock(return_value=0)
    fake_job = MagicMock()
    fake_job.id = str(uuid.uuid4())
    q.enqueue.return_value = fake_job
    return q


@pytest.fixture()
def app_client(mock_rq_queue: MagicMock) -> Generator[TestClient, None, None]:
    """
    TestClient with all external I/O patched:
      - PostgreSQL connection pool    → MagicMock
      - RQ Queue                      → mock_rq_queue fixture
      - queries.get_verification_by_ingest_id → returns None (no duplicate)
      - queries.insert_verification   → returns a fake row
      - queries.insert_claims         → no-op
    """
    with (
        patch("api.db.connection.init_pool"),
        patch("api.db.connection.close_pool"),
        patch("api.routes.verify._get_rq_queue", return_value=mock_rq_queue),
        patch(
            "api.db.queries.get_verification_by_ingest_id",
            return_value=None,
        ),
        patch(
            "api.db.queries.insert_verification",
            side_effect=lambda **kw: _make_verification_row(
                ingest_id=kw["ingest_id"],
                claim_count=kw["claim_count"],
            ),
        ),
        patch("api.db.queries.insert_claims"),
    ):
        from api.main import app
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


@pytest.fixture()
def sample_ingest_id() -> str:
    return f"ingest-pytest-{uuid.uuid4().hex[:8]}"
