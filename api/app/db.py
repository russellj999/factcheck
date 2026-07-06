"""
SQLite helper layer.
Uses WAL mode for better read/write concurrency when the worker
and API process share the same file.
"""

import sqlite3
import logging
from contextlib import contextmanager
from app.config import settings   # ← FIXED

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    """Yield a committed-or-rolled-back SQLite connection."""
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # rows act like dicts
    conn.execute("PRAGMA journal_mode=WAL") # concurrent reader + writer safe
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def insert_factcheck(post_id: str) -> dict:
    """Insert a fresh pending row. Raises sqlite3.IntegrityError on dup."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO factchecks (post_id, status) VALUES (?, 'pending')",
            (post_id,),
        )
        row = conn.execute(
            "SELECT * FROM factchecks WHERE post_id = ?", (post_id,)
        ).fetchone()
        return dict(row)


def get_factcheck(post_id: str) -> dict | None:
    """Return the factcheck row or None if it doesn't exist."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM factchecks WHERE post_id = ?", (post_id,)
        ).fetchone()
        return dict(row) if row else None


def update_factcheck(post_id: str, **fields) -> None:
    """
    Update arbitrary columns on a factcheck row.
    Example: update_factcheck("post-1001", status="done", verdict="true")
    """
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    set_clause += ", updated_at = datetime('now')"
    values = list(fields.values()) + [post_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE factchecks SET {set_clause} WHERE post_id = ?",
            values,
        )

