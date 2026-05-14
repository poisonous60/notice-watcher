"""LLM 호출 기록을 sqlite (`output/usage.sqlite3`) 에 append.

설계:
- N100 (운영 머신) 에서 매 호출 1행씩 INSERT. dev박스는 `inspect_subs.py pull` 로 끌어와 dashboard 가 read-only 표시.
- bot.sqlite3 와 분리 — 사용자 데이터 ≠ 운영 메트릭.
- WAL 모드 → 잦은 INSERT + dashboard 가 `.backup` 으로 pull 안전.
- 인덱스: `(ts)`, `(call_site, ts)` — 시계열·매트릭스 쿼리.
- 실패 격리: `LLMClient._record_safe` 가 예외 잡음. 여기선 단순 INSERT.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,          -- ISO-8601 UTC
    call_site       TEXT NOT NULL,          -- config_generate / config_retry / notify_summarize / notify_filter / legacy
    slug            TEXT,
    attempt         INTEGER DEFAULT 1,
    provider        TEXT NOT NULL,          -- gemini / openrouter
    model           TEXT NOT NULL,
    raw_model       TEXT,                   -- provider 가 알려준 정확 모델명 (별칭 해석 결과)
    status          TEXT NOT NULL,          -- ok / quota_429 / http_error / parse_error / network / other
    prompt_tokens   INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    prompt_chars    INTEGER DEFAULT 0,
    response_chars  INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    cost_usd        REAL,
    key_idx         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_site_ts ON llm_calls(call_site, ts);
"""


class UsageRecorder:
    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def write(self, *, call_site: str, slug: Optional[str], attempt: int,
              provider: str, model: str, raw_model: str, status: str,
              prompt_tokens: int, completion_tokens: int, total_tokens: int,
              prompt_chars: int, response_chars: int,
              latency_ms: int, cost_usd: Optional[float],
              key_idx: Optional[int]) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO llm_calls "
                "(ts, call_site, slug, attempt, provider, model, raw_model, status, "
                "prompt_tokens, completion_tokens, total_tokens, "
                "prompt_chars, response_chars, latency_ms, cost_usd, key_idx) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, call_site, slug, attempt, provider, model, raw_model, status,
                 prompt_tokens, completion_tokens, total_tokens,
                 prompt_chars, response_chars, latency_ms, cost_usd, key_idx),
            )


def default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "output" / "usage.sqlite3"


_default: Optional[UsageRecorder] = None


def get_default_recorder() -> UsageRecorder:
    """프로세스 전역 lazy recorder. notify/generator/bot 셋이 같은 인스턴스를 공유.

    sqlite WAL 모드라 동시 writer 안전. 한 프로세스 안에서 매번 새로 만들 필요 X.
    """
    global _default
    if _default is None:
        _default = UsageRecorder(default_db_path())
    return _default


__all__ = ["UsageRecorder", "default_db_path", "get_default_recorder"]
