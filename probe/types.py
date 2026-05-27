from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Classification(str, Enum):
    OK = "OK"
    BLOCKED_BOT = "BLOCKED_BOT"
    BLOCKED_IP = "BLOCKED_IP"
    BLOCKED_GEO = "BLOCKED_GEO"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_INCOMPATIBLE = "METHOD_INCOMPATIBLE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class Result:
    strategy: str                       # "S1.H3", "S4", "S5", "Jina", "Crawl4AI", ...
    target: str                         # "list" | "article" | "baseline" | "replay"
    url: str
    final_url: Optional[str] = None      # after redirects/navigation, if different or known
    status: Optional[int] = None
    duration_ms: int = 0
    body_path: Optional[str] = None     # 디스크 저장된 응답 본문 경로
    headers: dict[str, str] = field(default_factory=dict)
    classification: Classification = Classification.UNKNOWN_ERROR
    notable: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


@dataclass
class Diagnosis:
    slug: str
    url: str
    verdict: str
    recommended_strategy: str
    recommended_headers_summary: str
    recommended_polling_interval_sec: int
    list_candidates_summary: str
    article_entry_ok: bool
    notes: list[str] = field(default_factory=list)
