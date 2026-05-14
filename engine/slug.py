"""URL → slug (`<platform>_<board-id>_<hash>`) 변환 단일 source.

설계 의도:
  - 기존 `host_path_query` raw 형태 slug 는 60~100자로 길고 percent-encoded 한글이 뒤죽박죽,
    Discord `/report` autocomplete 의 100자 hard limit 도 자주 넘김 → 사용자가 보는 `/list`
    표시도 지저분.
  - 새 형식: `<platform>_<board-id>_<hash>`. 짧고 (보통 30~60자), 사람이 어떤 사이트인지
    한눈에 알 수 있고, hash 로 충돌 0.

스키마:
  platform  : `engine.recognizers.NAME` (recognized 면) 또는 `host_<host-dashed>` (unrecognized)
  board-id  : 각 recognizer 의 `_slug_board` 키 (cfg 에 들어옴) 또는 path 첫 segment (fallback)
  hash      : `sha1(canonical_url)[:8]` — 같은 URL ↔ 같은 slug. 같은 platform+board 안의
              variant (예: arca 채널의 category 탭) 도 hash 차이로 분리.

길이 budget (총 100자 cap):
  platform ≤ PLATFORM_BUDGET (=20)
  board    ≤ BOARD_BUDGET    (=60)
  hash       HASH_LEN        (=8)
  separators _ × 2           = 2
  → 합 ≤ 90 (10자 여유)

sanitize 룰: `[^A-Za-z0-9._%-]+ → _` (`%` 허용 — URL-encoded 한글 그대로 보존).

호출 흐름:
  bot/main.py `/watch`·`/preview`·`/unwatch` → probe.paths.url_to_slug → engine.slug.url_to_slug
  scripts/register.py, scripts/probe.py 등도 동일 경로.

마이그레이션: recognizer 의 PATTERNS/builder/_slug_board 가 바뀌면 같은 URL 의 slug 가 변할 수 있으므로
`scripts/migrate_slug_schema.py` 재실행 필요. 그 스크립트는 idempotent.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from engine.recognizers import recognize

PLATFORM_BUDGET = 20
BOARD_BUDGET = 60
HASH_LEN = 8
SLUG_MAX = 100

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._%-]+")
_MULTI_SLASH_RE = re.compile(r"/+")


def canonical_url(url: str) -> str:
    """결정적 URL 정규화 — slug hash 의 입력. 같은 의미의 URL → 같은 정규화 출력.

    - scheme 무시 (http vs https 가 같은 사이트로 취급 — 대부분 https redirect)
    - host lowercase
    - fragment 제거
    - path 의 `//+` → `/` 정규화 + trailing `/` 제거 (root 만 유지)
    - query 파라미터: 빈 값(`?a=`) 제거 + 키 정렬 → `?p=2&q=1` 과 `?q=1&p=2` 같음
    """
    sp = urlsplit(url.strip())
    netloc = sp.netloc.lower()
    path = _MULTI_SLASH_RE.sub("/", sp.path) or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    pairs = sorted(
        (k, v) for k, v in parse_qsl(sp.query, keep_blank_values=True) if v != ""
    )
    return (
        f"//{netloc}{path}"
        + (f"?{urlencode(pairs)}" if pairs else "")
    )


def _seg(s: str, max_len: int) -> str:
    """slug 한 segment 의 sanitize + truncate. 빈 결과면 'x' 반환(슬러그 비어선 안 됨).

    `%` 는 허용 — URL-encoded 한글(`%EA%B3%B5%EC%8B%9D` 같은) 그대로 보존하기 위함.
    """
    s = _SANITIZE_RE.sub("_", s or "").strip("_")
    if not s:
        return "x"
    return s[:max_len]


def _board_id_for(cfg: dict) -> str:
    """recognizer cfg → board-id 문자열.

    우선순위:
      1. cfg["_slug_board"] — recognizer 가 명시한 board 식별자 (slug 친화 형태로 미리 준비됨)
      2. cfg["board"] — `/` 와 `:` 만 `_` 로 치환 (예: naver-game-lounge 의 `lounge/Trickcal/3`)
    """
    if "_slug_board" in cfg:
        return str(cfg["_slug_board"])
    return str(cfg.get("board", "x")).replace("/", "_").replace(":", "_")


def _fallback_platform_board(url: str) -> tuple[str, str]:
    """recognizer 매칭 실패 시: `host_<host-dashed>` + first-path-segment.

    예:
      https://cse.skku.edu/cse/notice.do?...  →  ("host_cse-skku-edu", "cse")
      https://endfield.gryphline.com/ko-kr/news  →  ("host_endfield-gryphline-com", "ko-kr")
      https://www.gamemeca.com/news.php?ca=P  →  ("host_gamemeca-com", "news.php")
    """
    sp = urlsplit(url)
    host = sp.netloc.lower()
    # 공통 prefix 제거 (www. / m.) — 같은 사이트의 모바일/PC 가 같은 platform 으로 보이게
    for pre in ("www.", "m."):
        if host.startswith(pre):
            host = host[len(pre):]
            break
    host_dashed = host.replace(".", "-")
    path = sp.path.strip("/")
    seg = path.split("/", 1)[0] if path else "root"
    return f"host_{host_dashed}", seg


def platform_and_board(url: str) -> tuple[str, str]:
    """slug 의 platform + board 부분만 (hash 없이) 반환. UI 표시·디버깅용."""
    cfg = recognize(url)
    if cfg is not None:
        return str(cfg.get("_recognized_platform", "?")), _board_id_for(cfg)
    return _fallback_platform_board(url)


def url_to_slug(url: str) -> str:
    """URL → `<platform>_<board-id>_<hash>` (100자 이내).

    1. `engine.recognizers.recognize(url)` 로 plaform 매칭 시도.
       - 매칭되면 cfg["_recognized_platform"] + `_board_id_for(cfg)` 사용.
       - 매칭 안 되면 host + first-path-segment fallback.
    2. hash = `sha1(canonical_url(url))[:8]` — 같은 URL → 같은 slug 보장.
    3. 각 segment 를 sanitize + budget 으로 truncate, `_` 로 join.

    예시:
      arca.live/b/trickcal              → "arca-live_trickcal_<hash>"
      arca.live/b/trickcal?category=공식 → "arca-live_trickcal_%EA%B3%B5%EC%8B%9D_<hash>"
      cse.skku.edu/cse/notice.do?...    → "host_cse-skku-edu_cse_<hash>"
    """
    cfg = recognize(url)
    if cfg is not None:
        platform = str(cfg.get("_recognized_platform", "x"))
        board = _board_id_for(cfg)
    else:
        platform, board = _fallback_platform_board(url)
    h = hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:HASH_LEN]
    p = _seg(platform, PLATFORM_BUDGET)
    b = _seg(board, BOARD_BUDGET)
    slug = f"{p}_{b}_{h}"
    return slug[:SLUG_MAX]
