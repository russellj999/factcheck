import uuid
from rq import Queue
from redis import Redis

redis_conn = Redis(host="redis", port=6379)
extract_queue = Queue("extract", connection=redis_conn)

def enqueue_extract_job(text: str) -> str:
    job_id = f"ext-{uuid.uuid4()}"
    # Correct RQ import path
    extract_queue.enqueue("worker.extract.run_extract", text, job_id=job_id)
    return job_id
