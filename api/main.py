"""
main.py — FastAPI application entry point for Tier-2 Fact-Check API.

Startup sequence:
  1. Configure JSON logging.
  2. Initialise the PostgreSQL connection pool.
  3. Mount routers.
  4. Expose /healthz for liveness probes.
"""
from __future__ import annotations

import uvicorn
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.config import API_HOST, API_PORT, LOG_LEVEL
from api.db.connection import close_pool, init_pool
from api.logging_config import configure_logging, get_logger

# Routers
from api.routes.verify import router as verify_router
from api.routes.extract import router as extract_router   # <-- ADDED

# ---------------------------------------------------------------------------
# Logging — must be first so every subsequent import can log
# ---------------------------------------------------------------------------
configure_logging(LOG_LEVEL)
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated on_event handlers
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Fact-Check Tier-2 API.")
    init_pool()
    yield
    logger.info("Shutting down Fact-Check Tier-2 API.")
    close_pool()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Fact-Check LLM — Tier-2 Verify API",
    description=(
        "Accepts claim batches from the upstream ingest pipeline, "
        "persists them in Postgres, and enqueues RQ jobs for async fact-checking."
    ),
    version="0.1.0-checkpoint-a",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(verify_router)
app.include_router(extract_router)   # <-- ADDED


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/healthz", tags=["ops"], summary="Liveness probe")
async def healthz() -> JSONResponse:
    """Returns 200 OK when the API process is alive."""
    return JSONResponse({"status": "ok", "version": app.version})


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_config=None,  # suppress uvicorn default logging; use our JSON formatter
    )