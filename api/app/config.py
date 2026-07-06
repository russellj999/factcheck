from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str          = "redis://localhost:6379/0"
    sqlite_path: str        = "./factcheck.db"
    redis_lock_ttl: int     = 300          # seconds — lock + payload TTL
    worker_queue_name: str  = "factcheck"
    max_attempts: int       = 3

    model_config = {"env_file": ".env"}


settings = Settings()
