from rq import Worker, Queue
from redis import Redis

redis_conn = Redis(host="redis", port=6379)

verify_queue = Queue("verify", connection=redis_conn)
extract_queue = Queue("extract", connection=redis_conn)

if __name__ == "__main__":
    worker = Worker([verify_queue, extract_queue], connection=redis_conn)
    worker.work()
