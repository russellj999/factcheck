from pydantic import BaseModel

class ExtractRequest(BaseModel):
    text: str

class ExtractResponse(BaseModel):
    extract_job_id: str
    status: str = "queued"
