"""
config.py — centralised environment-variable configuration.

All defaults are safe for local docker-compose development.
Override via environment variables or a .env file loaded by docker-compose.
"""
import os

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "factcheck")
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "factcheck")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "factcheck")

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

# ---------------------------------------------------------------------------
# Redis / RQ
# ---------------------------------------------------------------------------
REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL: str = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")

RQ_QUEUE_NAME: str = os.getenv("RQ_QUEUE_NAME", "verify")
RQ_JOB_TIMEOUT: int = int(os.getenv("RQ_JOB_TIMEOUT", "300"))  # seconds

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
IDEMPOTENCY_CHECK: bool = os.getenv("IDEMPOTENCY_CHECK", "true").lower() == "true"
