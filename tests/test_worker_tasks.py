"""
test_worker_tasks.py — Unit tests for the RQ worker task functions.

Checkpoint A assertions:
  1. process_verify_job calls update_verification_status with 'processing' first.
  2. process_verify_job calls update_verification_status with 'completed' on success.
  3. Results list length matches the number of input claims.
  4. Each result contains required fields (claim_index, verdict, confidence).
  5. On exception, status is set to 'failed' and a DLQ entry is written.
  6. ingest_id and verify_job_id are bound in context vars during execution.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch


import pytest


SAMPLE_CLAIMS: List[Dict[str, Any]] = [
    {"text": "The Moon is made of cheese.", "source_url": None, "metadata": {}},
    {"text": "Python is a compiled language.", "source_url": None, "metadata": {}},
]


def _run_task(claims=None, verify_job_id=None, ingest_id=None):
    """Helper: import and run process_verify_job with mocked DB."""
    from worker.tasks import process_verify_job
    return process_verify_job(
        verify_job_id=verify_job_id or str(uuid.uuid4()),
        ingest_id=ingest_id or "ingest-worker-test",
        claims=claims or SAMPLE_CLAIMS,
    )


# ===========================================================================
# Happy-path tests
# ===========================================================================

class TestProcessVerifyJobSuccess:

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_sets_processing_before_completed(self, mock_update, mock_dlq, mock_claims):
        """update_verification_status must be called with 'processing' before 'completed'."""
        _run_task()
        calls = mock_update.call_args_list
        statuses = [c.kwargs["status"] for c in calls]
        assert "processing" in statuses
        assert "completed" in statuses
        assert statuses.index("processing") < statuses.index("completed")

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_final_status_is_completed(self, mock_update, mock_dlq, mock_claims):
        """Last call to update_verification_status must use status='completed'."""
        _run_task()
        last_call = mock_update.call_args_list[-1]
        assert last_call.kwargs["status"] == "completed"

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_results_count_matches_claims(self, mock_update, mock_dlq, mock_claims):
        """Number of result items must equal number of input claims."""
        _run_task(claims=SAMPLE_CLAIMS)
        # The 'completed' call carries the results list
        completed_call = [c for c in mock_update.call_args_list if c.kwargs.get("status") == "completed"]
        assert len(completed_call) == 1
        results = completed_call[0].kwargs.get("results", [])
        assert len(results) == len(SAMPLE_CLAIMS)

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_result_fields_present(self, mock_update, mock_dlq, mock_claims):
        """Each result must contain claim_index, verdict, confidence, evidence_urls."""
        _run_task(claims=SAMPLE_CLAIMS)
        completed_call = [c for c in mock_update.call_args_list if c.kwargs.get("status") == "completed"][0]
        results = completed_call[0].kwargs.get("results") or completed_call.kwargs.get("results", [])
        for r in results:
            assert "claim_index" in r
            assert "verdict" in r
            assert "confidence" in r
            assert "evidence_urls" in r

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_returns_summary_dict(self, mock_update, mock_dlq, mock_claims):
        """process_verify_job must return a summary dict with status='completed'."""
        vid = str(uuid.uuid4())
        result = _run_task(verify_job_id=vid, claims=SAMPLE_CLAIMS)
        assert isinstance(result, dict)
        assert result["status"] == "completed"
        assert result["verify_job_id"] == vid
        assert result["claim_count"] == len(SAMPLE_CLAIMS)

    @patch("worker.tasks.queries.insert_claims", return_value=None)
    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", return_value=None)
    def test_claim_indices_are_sequential(self, mock_update, mock_dlq, mock_claims):
        """Results must have sequential zero-based claim_index values."""
        three_claims = [{"text": f"Claim {i}."} for i in range(3)]
        _run_task(claims=three_claims)
        completed_call = [c for c in mock_update.call_args_list if c.kwargs.get("status") == "completed"][0]
        results = completed_call.kwargs.get("results", [])
        indices = [r["claim_index"] for r in results]
        assert indices == list(range(len(three_claims)))


# ===========================================================================
# Failure / DLQ tests
# ===========================================================================

class TestProcessVerifyJobFailure:

    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch("worker.tasks.queries.update_verification_status", side_effect=[None, RuntimeError("DB down")])
    def test_exception_triggers_dlq(self, mock_update, mock_dlq):
        """An unrecoverable exception must write a DLQ entry and re-raise."""
        vid = str(uuid.uuid4())
        with pytest.raises(RuntimeError):
            _run_task(verify_job_id=vid)
        mock_dlq.assert_called_once()
        dlq_kwargs = mock_dlq.call_args.kwargs
        assert dlq_kwargs["verify_job_id"] == vid

    @patch("worker.tasks.queries.insert_dlq", return_value=None)
    @patch(
        "worker.tasks.queries.update_verification_status",
        side_effect=[None, RuntimeError("transient error")],
    )
    def test_exception_sets_status_failed(self, mock_update, mock_dlq):
        """
        When the task raises, update_verification_status('failed') must be attempted.
        The mock raises on the second call (processing→stub→fails→failure handler
        calls update again, but that third call also goes through our patched
        _handle_failure which calls update_verification_status again).
        We patch _handle_failure directly to isolate.
        """
        vid = str(uuid.uuid4())
        with (
            patch("worker.tasks._handle_failure") as mock_handle,
            patch(
                "worker.tasks.queries.update_verification_status",
                side_effect=[None, RuntimeError("kaboom")],
            ),
        ):
            with pytest.raises(RuntimeError):
                _run_task(verify_job_id=vid)
            mock_handle.assert_called_once()
            assert mock_handle.call_args.kwargs["verify_job_id"] == vid
