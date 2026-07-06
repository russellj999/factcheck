from typing import Optional
from pydantic import BaseModel, Field

class IngestRequest(BaseModel):
    post_id: str

    content: Optional[str] = None
    original_text: Optional[str] = None
    translated_text: Optional[str] = None

    ingest_id: Optional[str] = None
    detected_language: Optional[str] = None
    post_type: Optional[str] = None
    content_type: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None


class IngestResponse(BaseModel):
    post_id: str
    status: str
    message: str


class FactCheckResponse(BaseModel):
    post_id:    str
    status:     str
    verdict:    Optional[str]   = None
    confidence: Optional[float] = None
    tier:       Optional[int]   = None
    attempts:   int
    error:      Optional[str]   = None
    created_at: str
    updated_at: str