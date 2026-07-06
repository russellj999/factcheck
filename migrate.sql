-- ============================================================
-- Fact-Check SQLite Schema
-- Run once: sqlite3 factcheck.db < migrate.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS factchecks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT    NOT NULL UNIQUE,           -- e.g. "post-1001"
    status      TEXT    NOT NULL DEFAULT 'pending', -- pending | processing | done | failed
    verdict     TEXT,                               -- true | false | mixed | unverifiable
    confidence  REAL,                               -- 0.0 – 1.0
    tier        INTEGER,                            -- 1 = Tier-1 resolved, 2 = escalated
    attempts    INTEGER NOT NULL DEFAULT 0,         -- retry counter
    error       TEXT,                               -- last error message
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_factchecks_post_id  ON factchecks(post_id);
CREATE INDEX IF NOT EXISTS idx_factchecks_status   ON factchecks(status);
