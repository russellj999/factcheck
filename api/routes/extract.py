from fastapi import APIRouter
from api.schemas.extract import ExtractRequest, ExtractResponse
from worker.enqueue import enqueue_extract_job

router = APIRouter()

@router.post("/extract", response_model=ExtractResponse)
async def extract_claims(request: ExtractRequest):
    job_id = enqueue_extract_job(request.text)
    return ExtractResponse(extract_job_id=job_id)
