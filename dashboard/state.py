"""snapshot 경로·DB 커넥션·마지막 pull 시각·FAILED 목록 헬퍼.

snapshot 위치는 `scripts/inspect_subs.py` 와 동일 — 사이드 by 사이드로 쓰임 (CLI 가 pull 떨궈도
대시보드가 즉시 본다).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bot import inspector

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "output" / "snapshot"
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"

# slug 형식: `<platform>_<board-id>_<hash>` 또는 `host_<host-dashed>_<seg>_<hash>` (docs/운영 메모.md §6).
# 허용 문자 = `engine.slug._SANITIZE_RE` 와 동일: 영숫자·점·언더스코어·하이픈·`%`(percent-encoded
# UTF-8 segment, 예: `_%EA%B3%B5_`). 100자 cap 은 engine.slug 에서 보장.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._%\-]{1,200}$")


def safe_slug(slug: str) -> bool:
    """URL path 로 받은 slug 가 파일시스템에 안전한지 확인. 실패 시 라우트가 404 반환."""
    return bool(_SLUG_RE.match(slug or ""))


def snapshot_paths() -> inspector.InspectorPaths:
    return inspector.InspectorPaths(
        db_path=SNAPSHOT_DIR / "bot.sqlite3",
        configs_dir=CONFIGS_SNAPSHOT,
        state_dir=SNAPSHOT_DIR / "poll_state",
    )


def snapshot_db_path() -> Path:
    return SNAPSHOT_DIR / "bot.sqlite3"


def usage_db_path() -> Path:
    """`inspect_subs.py pull` 이 N100 의 output/usage.sqlite3 사본을 떨궈둠.
    파일 없으면 LLM 호출이 아직 없거나 pull 안 했다는 뜻 — /usage 페이지가 안내."""
    return SNAPSHOT_DIR / "usage.sqlite3"


def snapshot_exists() -> bool:
    return snapshot_db_path().exists()


def open_conn():
    """매 요청마다 새 sqlite 커넥션. `bot.db.connect` 는 기본 `check_same_thread=True` 라
    FastAPI 의 threadpool dep 와 async handler 가 다른 스레드를 쓰면 `ProgrammingError` 발생 —
    dashboard 는 read-only snapshot 이라 `check_same_thread=False` 로 직접 연다.

    snapshot 없으면 None 반환 (라우트가 안내 페이지로 분기)."""
    p = snapshot_db_path()
    if not p.exists():
        return None
    conn = sqlite3.connect(str(p), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def last_pull_dt() -> Optional[datetime]:
    p = snapshot_db_path()
    if not p.exists():
        return None
    ts = p.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()


def last_pull_str() -> str:
    dt = last_pull_dt()
    if dt is None:
        return "(snapshot 없음 — Pull 먼저)"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def failed_slugs() -> list[str]:
    """state_dir 의 `*.FAILED.json` → slug 목록."""
    paths = snapshot_paths()
    if not paths.state_dir.exists():
        return []
    out = []
    for f in paths.state_dir.glob("*.FAILED.json"):
        out.append(f.name[: -len(".FAILED.json")])
    return sorted(out)


def failed_payload(slug: str) -> Optional[dict]:
    paths = snapshot_paths()
    p = paths.state_dir / f"{slug}.FAILED.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def unique_slugs(conn) -> list[str]:
    """현재 누군가 구독중인 distinct slug."""
    rows = conn.execute("SELECT DISTINCT slug FROM subscriptions ORDER BY slug").fetchall()
    return [r[0] for r in rows]
