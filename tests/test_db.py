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


def test_startup_objects_are_kept_out_of_garbage_collection(tmp_path):
    # With the 10k-film graph loaded, one full collection pass took ~750 ms and landed
    # inside random requests. Freezing what startup built makes those passes ~0 ms.
    import gc
    from fastapi.testclient import TestClient
    from watchtogether.api import create_app
    gc.unfreeze()
    with TestClient(create_app(tmp_path)):
        assert gc.get_freeze_count() > 1000


def test_cleanup_closes_its_checkpoint_connection(tmp_path):
    db = Database(tmp_path / "rooms.sqlite3")
    db.cleanup()
    db.close()
    assert not (tmp_path / "rooms.sqlite3-wal").exists()  # an unclosed connection would keep it
