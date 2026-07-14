"""
schemas.py — Pydantic request/response models for the Verify API.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DLQ = "dlq"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    """A single atomic claim to be fact-checked."""

    text: str = Field(..., min_length=1, max_length=4096, description="The claim text.")
    source_url: Optional[str] = Field(None, description="Optional URL the claim was extracted from.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class VerifyRequest(BaseModel):
    """
    POST /verify — submit a batch of claims for verification.

    `ingest_id` is the idempotency key supplied by the upstream ingest pipeline.
    Duplicate submissions with the same ingest_id return the existing job record
    rather than creating a new one.
    """

    ingest_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Idempotency key from the upstream ingest stage.",
        examples=["ingest-2024-abc123"],
    )
    claims: List[Claim] = Field(..., min_length=1, description="One or more claims to verify.")
    priority: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Job priority (0 = normal, 10 = highest).",
    )
    callback_url: Optional[str] = Field(
        None,
        description="Optional webhook URL to POST results to when the job completes.",
    )

    @field_validator("ingest_id")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class VerifyAccepted(BaseModel):
    """Returned immediately (HTTP 202) after enqueuing."""

    verify_job_id: UUID
    ingest_id: str
    status: JobStatus = JobStatus.QUEUED
    queue_position: Optional[int] = Field(None, description="Approximate queue depth at submission time.")
    message: str = "Job accepted and queued for processing."


class ClaimResult(BaseModel):
    """Result for a single claim within a completed job."""

    claim_index: int
    claim_text: str
    verdict: Optional[str] = None          # e.g. "TRUE" | "FALSE" | "UNVERIFIABLE"
    confidence: Optional[float] = None     # 0.0 – 1.0
    evidence_urls: Optional[List[str]] = None
    error: Optional[str] = None


class VerifyStatusResponse(BaseModel):
    """GET /verify/{verify_job_id} — full job status and results."""

    verify_job_id: UUID
    ingest_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    claim_count: int
    results: Optional[List[ClaimResult]] = None
    error_message: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
    ingest_id: Optional[str] = None
    verify_job_id: Optional[str] = None
