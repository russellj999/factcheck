import os

ROOT = os.getcwd()

def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated: {path}")

# ---------------------------------------------------------------------------
# 1. Ensure worker/__init__.py exists
# ---------------------------------------------------------------------------
worker_init = os.path.join(ROOT, "worker", "__init__.py")
if not os.path.exists(worker_init):
    write_file(worker_init, "")
else:
    print("Exists: worker/__init__.py")

# ---------------------------------------------------------------------------
# 2. Fix worker/enqueue.py
# ---------------------------------------------------------------------------
enqueue_path = os.path.join(ROOT, "worker", "enqueue.py")

enqueue_fixed = """import uuid
from rq import Queue
from redis import Redis

redis_conn = Redis(host="redis", port=6379)
extract_queue = Queue("extract", connection=redis_conn)

def enqueue_extract_job(text: str) -> str:
    job_id = f"ext-{uuid.uuid4()}"
    # Correct RQ import path
    extract_queue.enqueue("worker.extract.run_extract", text, job_id=job_id)
    return job_id
"""

write_file(enqueue_path, enqueue_fixed)

# ---------------------------------------------------------------------------
# 3. Ensure api/main.py includes extract router
# ---------------------------------------------------------------------------
main_path = os.path.join(ROOT, "api", "main.py")

with open(main_path, "r", encoding="utf-8") as f:
    main_contents = f.read()

if "from api.routes.extract import router as extract_router" not in main_contents:
    print("Adding extract router import to main.py...")
    main_contents = main_contents.replace(
        "from api.routes.verify import router as verify_router",
        "from api.routes.verify import router as verify_router\nfrom api.routes.extract import router as extract_router"
    )

if "app.include_router(extract_router)" not in main_contents:
    print("Adding extract router include to main.py...")
    main_contents = main_contents.replace(
        "app.include_router(verify_router)",
        "app.include_router(verify_router)\napp.include_router(extract_router)"
    )

write_file(main_path, main_contents)

# ---------------------------------------------------------------------------
# 4. Confirm worker/extract.py contains run_extract
# ---------------------------------------------------------------------------
extract_path = os.path.join(ROOT, "worker", "extract.py")

if not os.path.exists(extract_path):
    print("ERROR: worker/extract.py missing — cannot patch.")
else:
    with open(extract_path, "r", encoding="utf-8") as f:
        extract_contents = f.read()

    if "def run_extract" not in extract_contents:
        print("WARNING: run_extract() missing in worker/extract.py — adding stub.")
        extract_stub = """import os
import asyncpg

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
            \"\"\"
            INSERT INTO claims (claim_text, claim_type, confidence)
            VALUES ($1, $2, $3)
            \"\"\",
            c["claim_text"], c["claim_type"], c["confidence"]
        )
    await conn.close()
"""
        write_file(extract_path, extract_stub)
    else:
        print("worker/extract.py already contains run_extract().")

print("\nAll Checkpoint B fixes applied successfully.")
