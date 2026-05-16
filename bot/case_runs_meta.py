"""`output/cases.sqlite3` 의 case_runs 테이블 schema + outcome 상수 — *단일 진실원*.

`scripts/case_log.py`, `scripts/cases_index.py`, `dashboard/cases_view.py` 가 모두 이걸 import.
schema 변경 시 *오직 이 파일만* 갱신.

`docs/case_runs DB 계획.md` rev 2 (β minimal) 의 §1b 컬럼 그대로.
"""
from __future__ import annotations


OUTCOMES: tuple[str, ...] = (
    "improved",              # fix_layer 기반 코드 일반화 + 효과
    "handcrafted",           # 손-config / 손어댑터 — 그 사이트만 작동
    "no_change",             # 시도했지만 효과 X
    "rejected",              # 정책 거부 마커
    "rejected_with_policy",  # no-change 인데 영구 기록 가치 정책 결정
    "error",                 # skill 도중 미완 (정상 흐름엔 X)
)


OUTCOME_LABELS: dict[str, str] = {
    "improved":             "✨ improved",
    "handcrafted":          "🔧 handcrafted",
    "no_change":            "○ no_change",
    "rejected":             "🚫 rejected",
    "rejected_with_policy": "🚫📌 rejected+policy",
    "error":                "❌ error",
}

# OUTCOMES 와 OUTCOME_LABELS 키 동기성 — drift detect (import 시 즉시 fail)
assert set(OUTCOMES) == set(OUTCOME_LABELS), \
    f"OUTCOMES vs OUTCOME_LABELS drift: {set(OUTCOMES) ^ set(OUTCOME_LABELS)}"


SCHEMA: str = """
CREATE TABLE IF NOT EXISTS case_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    slug            TEXT NOT NULL,
    url             TEXT,
    skill           TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    failure_keys    TEXT,
    fix_layer       TEXT,
    files_changed   TEXT,
    case_md_slug    TEXT,
    reason          TEXT NOT NULL,
    requested_by    TEXT,
    commit_sha      TEXT,
    UNIQUE(slug, ts)
);
CREATE INDEX IF NOT EXISTS idx_case_runs_slug ON case_runs(slug);
CREATE INDEX IF NOT EXISTS idx_case_runs_ts ON case_runs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_case_runs_layer ON case_runs(fix_layer);
CREATE INDEX IF NOT EXISTS idx_case_runs_user ON case_runs(requested_by);
"""


def escape_like(value: str) -> str:
    """LIKE 패턴 wildcard escape — 사용자 input 의 `_`/`%`/`\\` 를 literal 로.
    SQL 측에서 `LIKE ? ESCAPE '\\\\'` 로 받아야 함.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
