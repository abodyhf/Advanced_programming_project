"""SQLite settings that keep each request from waiting on the disk."""
from watchtogether.db import Database


def test_commits_do_not_wait_for_fsync(tmp_path):
    db = Database(tmp_path / "rooms.sqlite3")
    with db.transaction() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL: fsync at checkpoints only
    db.close()


def test_wal_is_not_checkpointed_after_every_request(tmp_path):
    db = Database(tmp_path / "rooms.sqlite3")
    with db.transaction() as connection:
        connection.execute("INSERT INTO groups (id,title,owner_id,created_at,last_used) VALUES('g','t','o',0,0)")
    # Closing the last connection would checkpoint and delete the WAL (two more fsyncs per request).
    assert (tmp_path / "rooms.sqlite3-wal").exists()
    db.close()
    assert not (tmp_path / "rooms.sqlite3-wal").exists()
