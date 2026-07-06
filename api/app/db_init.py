from app.config import settings
import sqlite3, logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db(path):
    logger.info(f"Initializing DB at {path}")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS factchecks (
            id INTEGER PRIMARY KEY,
            post_id TEXT UNIQUE,
            status TEXT,
            verdict TEXT,
            confidence REAL,
            tier TEXT,
            attempts INTEGER DEFAULT 0,
            error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()
        logger.info("factchecks table ensured")
    finally:
        conn.close()

if __name__ == '__main__':
    init_db(settings.sqlite_path)
