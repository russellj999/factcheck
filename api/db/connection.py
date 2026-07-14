"""
connection.py — synchronous psycopg2 connection pool for the API and worker.

Uses a thread-safe SimpleConnectionPool so both the FastAPI process
(via sync threadpool) and the RQ worker (plain threads) share the same pattern.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

from api.config import DATABASE_URL
from api.logging_config import get_logger

logger = get_logger(__name__)

_pool: pg_pool.ThreadedConnectionPool | None = None
_lock = threading.Lock()

MIN_CONN = 1
MAX_CONN = 10


def init_pool() -> None:
    """Initialise the connection pool. Call once at startup."""
    global _pool
    with _lock:
        if _pool is None:
            logger.info("Initialising PostgreSQL connection pool.")
            _pool = pg_pool.ThreadedConnectionPool(
                MIN_CONN,
                MAX_CONN,
                dsn=DATABASE_URL,
                cursor_factory=RealDictCursor,
            )
            logger.info("PostgreSQL connection pool ready (min=%d, max=%d).", MIN_CONN, MAX_CONN)


def close_pool() -> None:
    """Close the connection pool. Call at shutdown."""
    global _pool
    with _lock:
        if _pool:
            _pool.closeall()
            _pool = None
            logger.info("PostgreSQL connection pool closed.")


@contextmanager
def get_conn() -> Generator:
    """
    Yield a checked-out connection; auto-commit on success, rollback on error.

    Usage::

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
