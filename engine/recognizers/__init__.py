"""알려진 플랫폼 인식기 — URL 이 *이미 손어댑터/검증된 config 패턴이 있는* 플랫폼이면
probe + Gemini 없이 config 를 바로 만들어 등록한다. `register.py` 가 probe 전에 `recognize()` 호출.

이 패키지는 서브모듈(`engine/recognizers/<plat>.py`)을 자동 발견해서 인식기를 모은다.
각 서브모듈이 export 해야 하는 것:
  - `NAME: str`                                   플랫폼 식별자 (예: "reddit", "naver-cafe")
  - `PATTERNS: list[tuple[re.Pattern, builder]]`  URL 패턴 + builder 함수
       builder: (re.Match, url) -> config dict | None
       매칭이 잘못됐을 가능성이 있으면 None 반환 → 일반 파이프라인 폴백.

builder 가 cfg 에 *선택적으로* 넣을 수 있는 키:
  - `_slug_board: str`  `engine.slug.url_to_slug` 가 slug 의 board 부분으로 쓰는 식별자.
                        없으면 `cfg["board"]` 의 `/` `:` 만 `_` 로 치환해 사용.
                        예) arca-live: `channel` (또는 `channel_<url-encoded-category>`),
                            naver-cafe: `cafe<id>_menu<id>`, dcinside-mgallery: `gallery_id`.
                        ⚠ PATTERNS / builder / `_slug_board` 식 어느 하나라도 바꾸면 *같은 URL 의 slug 가
                        달라질 수 있음* → `scripts/migrate_slug_schema.py` 재실행 필요 (idempotent).

새 플랫폼 추가:
  1. 손어댑터/손config 로 한 사이트 처리 후
  2. `engine/recognizers/<plat>.py` 한 개 신규 작성 — 비슷한 기존 파일을 참고하면 충분
     (기존 어떤 파일도 수정 안 함; auto-discovery 가 새 파일을 자동으로 잡음)
  3. 같은 플랫폼의 다른 게시판은 그 다음부터 인식기로 자동 매칭

레지스트리 순서: `NAME` 알파벳 정렬 (크로스-플랫폼 패턴 충돌 없음 — 다 host 기반).
한 파일 안의 `PATTERNS` 리스트 순서는 보존(naver-cafe 3변형 같은 경우 위에서부터 첫 매칭).
밑줄(`_`) 로 시작하는 모듈은 auto-discovery 에서 제외 (공용 헬퍼용).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from typing import Callable, Optional

log = logging.getLogger(__name__)


def _load() -> list[tuple[str, "re.Pattern", Callable[["re.Match", str], Optional[dict]]]]:
    items: list[tuple[str, "re.Pattern", Callable]] = []
    for mi in pkgutil.iter_modules(__path__):
        if mi.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{mi.name}")
        except Exception:  # noqa: BLE001  한 인식기가 import 에러 나도 나머지는 살아야 함
            log.exception("recognizers: %s import 실패 — 건너뜀", mi.name)
            continue
        name = getattr(mod, "NAME", mi.name)
        patterns = getattr(mod, "PATTERNS", None)
        if not patterns:
            log.debug("recognizers: %s 에 PATTERNS 없음 — 건너뜀", mi.name)
            continue
        for pat, builder in patterns:
            items.append((name, pat, builder))
    items.sort(key=lambda t: t[0])
    return items


_RECOGNIZERS = _load()


def _load_rejects() -> list[tuple[str, "re.Pattern", str, bool]]:
    """`PATTERNS_REJECT` 를 export 한 모듈을 모은다 — 단일 article URL fast-path 거부용.
    builder 없음. tuple 형식:
      - 2-tuple `(pattern, reason)` → skip_learn=False (default)
      - 3-tuple `(pattern, reason, skip_learn)` → skip_learn=True 면 `_learn_pattern` 호출 X.
    같은 첫 path segment 를 보드/article 이 공유하는 사이트는 skip_learn=True 박을 것
    (path_prefix 가 너무 좁아 보드 URL 까지 차단되는 걸 막음)."""
    items: list[tuple[str, "re.Pattern", str, bool]] = []
    for mi in pkgutil.iter_modules(__path__):
        if mi.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{mi.name}")
        except Exception:  # noqa: BLE001
            continue
        rejects = getattr(mod, "PATTERNS_REJECT", None)
        if not rejects:
            continue
        name = getattr(mod, "NAME", mi.name)
        for entry in rejects:
            if len(entry) == 2:
                pat, reason = entry
                skip_learn = False
            elif len(entry) == 3:
                pat, reason, skip_learn = entry
            else:
                log.warning("recognizers: %s PATTERNS_REJECT 항목 길이 %d 무시 (2 or 3 만 지원)", mi.name, len(entry))
                continue
            items.append((name, pat, reason, bool(skip_learn)))
    return items


_REJECTS = _load_rejects()


def recognize(url: str) -> Optional[dict]:
    """url 이 알려진 플랫폼이면 그 config dict(`_recognized_platform` 키 포함), 아니면 None."""
    if not url:
        return None
    for name, pat, builder in _RECOGNIZERS:
        m = pat.search(url)
        if not m:
            continue
        try:
            cfg = builder(m, url)
        except Exception:  # noqa: BLE001  builder 가 터지면 그 인식기는 건너뜀 → 폴백
            log.debug("recognizers: builder %r 예외 (url=%r)", name, url, exc_info=True)
            cfg = None
        if not cfg:
            continue
        cfg["_recognized_platform"] = name
        return cfg
    return None


def recognize_reject(url: str) -> Optional[tuple[str, str, bool]]:
    """url 이 알려진 단일 article 호스트 패턴이면 (NAME, reason, skip_learn). 아니면 None.
    `register.py` 가 probe 전에 호출 — 매칭 시 즉시 REJECTED (+ skip_learn=False 면 learned_blacklist 학습).
    위키 한글 `분류:`/`특수기능:` 같은 URL-encoded path 의 negative lookahead 매칭을 위해
    unquote 한 형태에 대해서만 검사 (raw % 이스케이프는 lookahead literal 과 매칭 안 되므로 통과 위험).

    skip_learn 의미: 같은 첫 path segment 를 보드/article 이 공유하는 사이트(nature/iln-ieee/jobplanet 등)는
    `_learn_pattern` 의 path_prefix(=첫 segment) 차단이 보드 URL 까지 막을 수 있어 skip — REJECTED 마커만 박는다.
    위키/지식백과/Britannica/USHMM 처럼 호스트 전체가 article-only 면 skip_learn=False (default — 전체 차단 OK)."""
    if not url:
        return None
    from urllib.parse import unquote
    try:
        decoded = unquote(url)
    except Exception:  # noqa: BLE001
        decoded = url
    for name, pat, reason, skip_learn in _REJECTS:
        if pat.search(decoded):
            return name, reason, skip_learn
    return None


def platform_names() -> list[str]:
    return list(dict.fromkeys(name for name, _, _ in _RECOGNIZERS))
