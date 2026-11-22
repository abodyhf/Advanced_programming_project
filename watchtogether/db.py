"""Durable room state. A transaction serializes each group mutation."""
from contextlib import contextmanager
import sqlite3
import time
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS groups (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, owner_id TEXT NOT NULL,
 phase TEXT NOT NULL DEFAULT 'collecting', created_at REAL NOT NULL,
 last_used REAL NOT NULL, recommendations TEXT NOT NULL DEFAULT '[]',
 winner TEXT, is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
 id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
 nickname TEXT NOT NULL, nickname_key TEXT NOT NULL, token_hash TEXT NOT NULL,
 likes TEXT NOT NULL DEFAULT '[]', dislikes TEXT NOT NULL DEFAULT '[]', rdf_ttl TEXT,
 UNIQUE(group_id, nickname_key)
);
CREATE TABLE IF NOT EXISTS votes (
 group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
 member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
 film_id TEXT NOT NULL, PRIMARY KEY(group_id, member_id)
);
CREATE INDEX IF NOT EXISTS member_group_idx ON members(group_id);
CREATE INDEX IF NOT EXISTS group_expiry_idx ON groups(last_used);
"""

class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        connection.executescript(SCHEMA)
        connection.close()
        # SQLite checkpoints and deletes the WAL when its last connection closes, which costs
        # extra fsyncs on every request. An idle connection keeps the WAL between requests.
        self._idle = sqlite3.connect(self.path, check_same_thread=False)  # never queried again, only closed
        self._idle.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()  # attach it to the WAL

    def close(self):
        self._idle.close()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        # WAL + NORMAL syncs at checkpoints, not every commit. The database stays consistent;
        # a power cut can lose the last few commits (votes), which is fine for a movie night.
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cleanup(self, now=None):
        cutoff = (time.time() if now is None else now) - 30 * 86400
        with self.transaction() as connection:
            count = connection.execute("DELETE FROM groups WHERE last_used < ?", (cutoff,)).rowcount
        # Make deleted profile bytes leave the WAL rather than waiting for the next checkpoint.
        with self.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return count
