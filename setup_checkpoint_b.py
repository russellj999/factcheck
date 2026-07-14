import os

# Root of Tier-2 project
ROOT = os.getcwd()

# Folder structure to create
folders = [
    "api/routes",
    "api/schemas",
    "worker",
    "samples"
]

for folder in folders:
    path = os.path.join(ROOT, folder)
    os.makedirs(path, exist_ok=True)
    print(f"Created folder: {path}")

# ---------------------------------------------------------------------------
# Write ExtractRequest + ExtractResponse schema
# ---------------------------------------------------------------------------
extract_schema = """from pydantic import BaseModel

class ExtractRequest(BaseModel):
    text: str

class ExtractResponse(BaseModel):
    extract_job_id: str
    status: str = "queued"
"""

with open("api/schemas/extract.py", "w") as f:
    f.write(extract_schema)
print("Created: api/schemas/extract.py")

# ---------------------------------------------------------------------------
# Write /extract API route
# ---------------------------------------------------------------------------
extract_route = """from fastapi import APIRouter
from api.schemas.extract import ExtractRequest, ExtractResponse
from worker.enqueue import enqueue_extract_job

router = APIRouter()

@router.post("/extract", response_model=ExtractResponse)
async def extract_claims(request: ExtractRequest):
    job_id = enqueue_extract_job(request.text)
    return ExtractResponse(extract_job_id=job_id)
"""

with open("api/routes/extract.py", "w") as f:
    f.write(extract_route)
print("Created: api/routes/extract.py")

# ---------------------------------------------------------------------------
# Write enqueue logic
# ---------------------------------------------------------------------------
enqueue_logic = """import uuid
from rq import Queue
from redis import Redis

redis_conn = Redis(host="redis", port=6379)
extract_queue = Queue("extract", connection=redis_conn)

def enqueue_extract_job(text: str) -> str:
    job_id = f"ext-{uuid.uuid4()}"
    extract_queue.enqueue("worker.extract.run_extract", text, job_id=job_id)
    return job_id
"""

with open("worker/enqueue.py", "w") as f:
    f.write(enqueue_logic)
print("Created: worker/enqueue.py")

# ---------------------------------------------------------------------------
# Write extraction worker logic
# ---------------------------------------------------------------------------
extract_worker = """import os
import asyncpg

# TODO: Replace with actual LLM call
def run_extract(text: str):
    claims = [
        {
            "claim_text": "The Earth is warming faster than expected.",
            "claim_type": "factual",
            "confidence": 0.92,
        },
        {
            "claim_text": "Apple will release a new iPhone next year.",
            "claim_type": "prediction",
            "confidence": 0.75,
        }
    ]
    import asyncio
    asyncio.run(save_claims_to_db(claims))
    return claims

async def save_claims_to_db(claims):
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    for c in claims:
        await conn.execute(
            \"""
            INSERT INTO claims (claim_text, claim_type, confidence)
            VALUES ($1, $2, $3)
            \""",
            c["claim_text"], c["claim_type"], c["confidence"]
        )
    await conn.close()
"""

with open("worker/extract.py", "w") as f:
    f.write(extract_worker)
print("Created: worker/extract.py")

# ---------------------------------------------------------------------------
# Write worker runner
# ---------------------------------------------------------------------------
run_worker = """from rq import Worker, Queue
from redis import Redis

redis_conn = Redis(host="redis", port=6379)

verify_queue = Queue("verify", connection=redis_conn)
extract_queue = Queue("extract", connection=redis_conn)

if __name__ == "__main__":
    worker = Worker([verify_queue, extract_queue], connection=redis_conn)
    worker.work()
"""

with open("worker/run_worker.py", "w") as f:
    f.write(run_worker)
print("Created: worker/run_worker.py")

# ---------------------------------------------------------------------------
# Write sample payload
# ---------------------------------------------------------------------------
sample_payload = """{
  "text": "The Earth is warming faster than expected. Apple will release a new iPhone next year."
}
"""

with open("samples/post_extract.json", "w") as f:
    f.write(sample_payload)
print("Created: samples/post_extract.json")

print("\nCheckpoint B setup complete.")
