"""알려진 백과/사전 호스트의 *단일 article URL* fast-path 거부.

이 모듈은 다른 인식기와 달리 *config 를 만들지 않는다* — `PATTERNS_REJECT` 를 export 해
`register.py` 가 probe 전에 `recognize_reject(url)` 으로 검사하고, 매칭 시 즉시
REJECTED.json marker + learned_blacklist 학습 후 종료.

이유: 위키/지식백과/Britannica/USHMM 같은 사이트의 단일 article 페이지는 in-text 링크가
같은 호스트로 5+개 나와 `_board_shape_check` 의 `n_html_same` 신호를 false-positive 로
통과시킨다(폴링 의미 없음 — 한 글 안의 참고 링크를 새 글로 감시). 손-거부 + learned_blacklist
의 반복을 막기 위해 호스트 단위로 PATTERNS 박는다.

새 호스트 추가 룰:
  - 사용자가 폴링 *목적으로 줄 가능성이 있는* 같은-host *목록* URL (분류/카테고리/Special)
    이 패턴에 안 걸려야 함 — `?!` 부정-look-ahead 로 명시 제외.
  - 단일 article URL 폼이 *명확* 해야 함 (path 1~2 segment, query 없이 또는 query-only).

이 PATTERNS 는 위에서부터 첫 매칭 — 다른 인식기(`PATTERNS`)보다 *먼저* 검사돼야 안전
(예: 위키 분류페이지를 board 로 등록하려는 시도가 있다면 이 모듈은 통과시키고 일반 파이프라인이 처리).
"""
from __future__ import annotations

import re

NAME = "article_page_reject"

PATTERNS_REJECT: list[tuple["re.Pattern[str]", str]] = [
    # Wikipedia (모든 lang) — `/wiki/<title>` 단일 article. Special:/Category:/Portal:/Help:/File:/Talk: 등 제외.
    (re.compile(
        r"^https?://[a-z]{2,3}\.wikipedia\.org/wiki/"
        r"(?!Special:|Category:|Portal:|Help:|File:|Talk:|User:|Wikipedia:|Template:|특수기능:|분류:|위키백과:)"
        r"[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "위키피디아 단일 article — 게시판 아님. 폴링 대상 X (한 글 안의 참고 링크를 새 글로 감시할 수 없음)."),
    # 네이버 지식백과 — `terms.naver.com/entry.naver?docId=...` 단일 항목.
    (re.compile(
        r"^https?://terms\.naver\.com/entry\.(?:naver|nhn)\b", re.I,
    ), "네이버 지식백과 단일 항목 — 게시판 아님. 폴링 대상 X."),
    # Britannica — `/event/<X>`, `/topic/<X>`, `/biography/<X>`, `/place/<X>`, `/art/<X>`, `/science/<X>`, `/technology/<X>`, `/animal/<X>`, `/plant/<X>` 단일 article.
    (re.compile(
        r"^https?://www\.britannica\.com/"
        r"(?:event|topic|biography|place|art|science|technology|animal|plant|sports|summary)/"
        r"[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "Britannica 단일 article — 게시판 아님. 폴링 대상 X."),
    # USHMM Encyclopedia — `/content/<lang>/article/<slug>` 단일 article.
    (re.compile(
        r"^https?://encyclopedia\.ushmm\.org/content/[a-z]+/article/[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "USHMM Encyclopedia 단일 article — 게시판 아님. 폴링 대상 X."),
]
