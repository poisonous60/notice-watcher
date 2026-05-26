import importlib.util
import sqlite3
from pathlib import Path


def _load_remote_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("notice_remote_for_test", root / "scripts" / "remote.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jobs_status_bucket_splits_capability_blocked_from_failed():
    remote = _load_remote_module()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE jobs("
        "kind TEXT, status TEXT, result_rc INTEGER, created_at TEXT, id INTEGER)"
    )
    conn.executemany(
        "INSERT INTO jobs(kind,status,result_rc,created_at,id) VALUES(?,?,?,?,?)",
        [
            ("register", "done", 0, "2026-05-26T00:00:00", 1),
            ("register", "failed", 1, "2026-05-26T00:00:01", 2),
            ("register", "failed", 5, "2026-05-26T00:00:02", 3),
            ("register", "pending", None, "2026-05-26T00:00:03", 4),
        ],
    )

    rows = conn.execute(
        f"SELECT {remote._jobs_status_bucket_expr()} AS status, COUNT(*) "
        "FROM jobs WHERE kind='register' GROUP BY 1"
    ).fetchall()

    assert dict(rows) == {"blocked": 1, "done": 1, "failed": 1, "pending": 1}
