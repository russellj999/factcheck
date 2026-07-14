"""
test_verify_endpoint.py — Unit tests for POST /verify and GET /verify/{id}.

Checkpoint A assertions:
  1. POST /verify returns HTTP 202.
  2. Response body contains verify_job_id (UUID), ingest_id, status=queued.
  3. RQ Queue.enqueue() is called exactly once with correct kwargs.
  4. DB insert_verification is called exactly once.
  5. Duplicate ingest_id returns same verify_job_id (idempotency).
  6. GET /verify/{id} returns job details when the row exists.
  7. GET /verify/{id} returns 404 when not found.
  8. POST /verify with empty claims list returns 422.
  9. POST /verify with missing ingest_id returns 422.
 10. GET /verify/<non-uuid> returns 422.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ===========================================================================
# POST /verify
# ===========================================================================

class TestPostVerify:

    def test_returns_202(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """POST /verify must return HTTP 202 Accepted."""
        response = app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [{"text": "The Earth is round."}],
            },
        )
        assert response.status_code == 202, response.text

    def test_response_body_schema(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """Response must include verify_job_id (UUID), ingest_id, and status=queued."""
        response = app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [{"text": "Water is wet."}],
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert "verify_job_id" in body
        assert "ingest_id" in body
        assert "status" in body
        # verify_job_id must be a valid UUID
        uuid.UUID(body["verify_job_id"])
        assert body["ingest_id"] == sample_ingest_id
        assert body["status"] == "queued"

    def test_rq_enqueue_called_once(
        self,
        app_client: TestClient,
        mock_rq_queue: MagicMock,
        sample_ingest_id: str,
    ) -> None:
        """RQ Queue.enqueue must be called exactly once per new job."""
        app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [{"text": "The sky is blue."}],
            },
        )
        mock_rq_queue.enqueue.assert_called_once()
        call_kwargs = mock_rq_queue.enqueue.call_args
        # First positional arg is the task path
        assert call_kwargs.args[0] == "worker.tasks.process_verify_job"

    def test_db_insert_called_once(self, sample_ingest_id: str, mock_rq_queue: MagicMock) -> None:
        """insert_verification must be called exactly once per POST."""
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
            patch("api.routes.verify._get_rq_queue", return_value=mock_rq_queue),
            patch("api.db.queries.get_verification_by_ingest_id", return_value=None),
            patch("api.db.queries.insert_claims"),
            patch(
                "api.db.queries.insert_verification",
                side_effect=lambda **kw: {
                    "verify_job_id": uuid.uuid4(),
                    "ingest_id": kw["ingest_id"],
                    "status": "queued",
                    "claim_count": kw["claim_count"],
                    "priority": kw["priority"],
                    "callback_url": kw["callback_url"],
                    "results": None,
                    "error_message": None,
                    "created_at": datetime.now(tz=timezone.utc),
                    "updated_at": datetime.now(tz=timezone.utc),
                },
            ) as mock_insert,
        ):
            from api.main import app
            with TestClient(app) as client:
                client.post(
                    "/verify",
                    json={
                        "ingest_id": sample_ingest_id,
                        "claims": [{"text": "Claim text."}],
                    },
                )
            mock_insert.assert_called_once()
            _, kwargs = mock_insert.call_args
            assert kwargs["ingest_id"] == sample_ingest_id
            assert kwargs["claim_count"] == 1

    def test_multiple_claims_accepted(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """Batch of 3 claims should return 202."""
        response = app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [
                    {"text": "Claim one."},
                    {"text": "Claim two."},
                    {"text": "Claim three."},
                ],
                "priority": 5,
            },
        )
        assert response.status_code == 202

    def test_idempotency_returns_existing_job(self, sample_ingest_id: str, mock_rq_queue: MagicMock) -> None:
        """
        When get_verification_by_ingest_id returns a row,
        POST /verify must return that existing row without a new DB insert.
        """
        existing_vid = uuid.uuid4()
        existing_row = {
            "verify_job_id": existing_vid,
            "ingest_id": sample_ingest_id,
            "status": "queued",
            "claim_count": 1,
            "priority": 0,
            "callback_url": None,
            "results": None,
            "error_message": None,
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
        }
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
            patch("api.routes.verify._get_rq_queue", return_value=mock_rq_queue),
            patch(
                "api.db.queries.get_verification_by_ingest_id",
                return_value=existing_row,
            ),
            patch("api.db.queries.insert_verification") as mock_insert,
        ):
            from api.main import app
            with TestClient(app) as client:
                response = client.post(
                    "/verify",
                    json={
                        "ingest_id": sample_ingest_id,
                        "claims": [{"text": "Any claim."}],
                    },
                )
            assert response.status_code == 202
            body = response.json()
            assert uuid.UUID(body["verify_job_id"]) == existing_vid
            # No new row should have been inserted
            mock_insert.assert_not_called()
            # No new RQ job should have been enqueued
            mock_rq_queue.enqueue.assert_not_called()

    # -----------------------------------------------------------------------
    # Validation / error cases
    # -----------------------------------------------------------------------

    def test_empty_claims_returns_422(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """An empty claims list must be rejected with HTTP 422."""
        response = app_client.post(
            "/verify",
            json={"ingest_id": sample_ingest_id, "claims": []},
        )
        assert response.status_code == 422

    def test_missing_ingest_id_returns_422(self, app_client: TestClient) -> None:
        """Omitting ingest_id must return HTTP 422."""
        response = app_client.post(
            "/verify",
            json={"claims": [{"text": "Some claim."}]},
        )
        assert response.status_code == 422

    def test_missing_claim_text_returns_422(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """A claim without `text` must be rejected with HTTP 422."""
        response = app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [{"source_url": "https://example.com"}],  # no 'text'
            },
        )
        assert response.status_code == 422

    def test_priority_out_of_range_returns_422(self, app_client: TestClient, sample_ingest_id: str) -> None:
        """Priority outside 0–10 must be rejected."""
        response = app_client.post(
            "/verify",
            json={
                "ingest_id": sample_ingest_id,
                "claims": [{"text": "Claim."}],
                "priority": 99,
            },
        )
        assert response.status_code == 422


# ===========================================================================
# GET /verify/{verify_job_id}
# ===========================================================================

class TestGetVerifyStatus:

    def _make_row(self, verify_job_id: str, ingest_id: str, status: str = "completed"):
        return {
            "verify_job_id": uuid.UUID(verify_job_id),
            "ingest_id": ingest_id,
            "status": status,
            "claim_count": 1,
            "priority": 0,
            "callback_url": None,
            "results": None,
            "error_message": None,
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
        }

    def test_returns_200_when_found(self, sample_ingest_id: str) -> None:
        """GET /verify/{id} returns 200 when the row exists."""
        vid = str(uuid.uuid4())
        row = self._make_row(vid, sample_ingest_id)
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
            patch("api.db.queries.get_verification_by_job_id", return_value=row),
        ):
            from api.main import app
            with TestClient(app) as client:
                response = client.get(f"/verify/{vid}")
            assert response.status_code == 200

    def test_response_schema_when_found(self, sample_ingest_id: str) -> None:
        """GET /verify/{id} response must include required fields."""
        vid = str(uuid.uuid4())
        row = self._make_row(vid, sample_ingest_id, status="queued")
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
            patch("api.db.queries.get_verification_by_job_id", return_value=row),
        ):
            from api.main import app
            with TestClient(app) as client:
                body = client.get(f"/verify/{vid}").json()
            assert uuid.UUID(body["verify_job_id"]) == uuid.UUID(vid)
            assert body["ingest_id"] == sample_ingest_id
            assert body["status"] == "queued"
            assert "created_at" in body
            assert "updated_at" in body
            assert "claim_count" in body

    def test_returns_404_when_not_found(self) -> None:
        """GET /verify/{id} returns 404 for unknown job ID."""
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
            patch("api.db.queries.get_verification_by_job_id", return_value=None),
        ):
            from api.main import app
            with TestClient(app) as client:
                response = client.get(f"/verify/{uuid.uuid4()}")
            assert response.status_code == 404

    def test_returns_422_for_non_uuid(self, sample_ingest_id: str) -> None:
        """GET /verify/<non-uuid> returns 422 Unprocessable Entity."""
        with (
            patch("api.db.connection.init_pool"),
            patch("api.db.connection.close_pool"),
        ):
            from api.main import app
            with TestClient(app) as client:
                response = client.get("/verify/not-a-valid-uuid")
            assert response.status_code == 422


# ===========================================================================
# Health check
# ===========================================================================

class TestHealthz:

    def test_healthz_returns_ok(self, app_client: TestClient) -> None:
        response = app_client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
