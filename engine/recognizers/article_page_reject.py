"""알려진 백과/사전 호스트의 *단일 article URL* fast-path 거부.

이 모듈은 다른 인식기와 달리 *config 를 만들지 않는다* — `PATTERNS_REJECT` 를 export 해
`register.py` 가 probe 전에 `recognize_reject(url)` 으로 검사하고, 매칭 시 즉시
REJECTED.json marker (+ skip_learn=False 면 learned_blacklist 학습) 후 종료.

이유: 위키/지식백과/Britannica/USHMM 같은 사이트의 단일 article 페이지는 in-text 링크가
같은 호스트로 5+개 나와 `_board_shape_check` 의 `n_html_same` 신호를 false-positive 로
통과시킨다(폴링 의미 없음 — 한 글 안의 참고 링크를 새 글로 감시). 손-거부 + learned_blacklist
의 반복을 막기 위해 호스트 단위로 PATTERNS 박는다.

PATTERN tuple 형식:
  - 2-tuple `(pattern, reason)` — skip_learn=False (default; `_learn_pattern` 호출).
  - 3-tuple `(pattern, reason, skip_learn=True)` — REJECTED 마커만 박고 learned_blacklist 학습 X.
    learned_blacklist 의 `_extract_url_pattern` 은 path 의 *첫 segment* 만 추출 (host 전체 안 막기 위해 보수적).
    이게 너무 *좁아도* 문제 — `/articles/<doi>` 한 글 거부가 `/articles?type=news` 보드 URL 까지
    같은 path_prefix `/articles` 로 묶여 차단됨. 호스트의 *전체 path-prefix* 가 article-only 가 아닌
    (보드와 article 이 같은 첫 segment 를 공유하는) 사이트는 skip_learn=True.

새 호스트 추가 룰 (skip_learn 결정 — 이 순서로 점검):

  1. **사용자가 폴링 *목적으로 줄 수 있는* 같은-host *목록* URL** (분류/카테고리/Special/lang index/
     보드 인덱스) 이 패턴에 안 걸려야 함 — `?!` 부정-look-ahead 또는 narrow pattern 으로 명시 제외.

  2. **단일 article URL 폼이 *명확*** 해야 함 (path 1~2 segment, query 없이 또는 query-only).

  3. **skip_learn 결정**:
     - 단일 article URL 의 *첫 path segment* 를 식별.
     - 그 첫 segment 로 시작하는 *다른* URL 폼이 정상 보드/인덱스가 될 수 있는가?
       - YES → `skip_learn=True` **필수** (3-tuple).
       - NO  → `skip_learn=False` (2-tuple OK; host 전체가 article-only).
     - 판정 기준: recognize_reject 가 보드를 통과시키는데 (test fixture 로 확인) learned_blacklist
       의 `_extract_url_pattern` (첫 segment 만) 으로 학습되면 그 보드까지 url_gate 에서 차단되는가?
       - 차단됨 → skip_learn=True. 안전 망 (반복 학습은 막되 잘못 학습은 안 함).
     - 예시:
       - wikipedia `/wiki/Article` article + `/wiki/Special:RecentChanges` 보드 → 같은 `/wiki` →
         skip_learn=True.
       - ushmm `/content/<lang>/article/<X>` article + `/content/<lang>` 인덱스 → 같은 `/content` →
         skip_learn=True.
       - nature `/articles/<doi>` article + `/articles?type=news` 보드 → 같은 `/articles` →
         skip_learn=True.
       - britannica `/event/<X>`, `/topic/<X>`, ... 각각 첫 segment 별 분리 → article-only →
         skip_learn=False (각 segment 가 모두 article).
       - github-wiki-see `/m/<user>/<repo>/wiki/` → host 전체가 wiki 미러 → skip_learn=False.

  4. **fixture 강제** — 새 호스트 추가 시 `tests/recognizers/test_article_page_reject.py` 에 두 개:
     - article URL → 거부 + `out[2]` (skip_learn) 값 명시 (`is True` 또는 `is False`).
     - 같은 host 의 *보드/인덱스* URL → 통과 (`out is None`). 같은 첫 segment 공유면 더 중요.

이 PATTERNS 는 위에서부터 첫 매칭 — 다른 인식기(`PATTERNS`)보다 *먼저* 검사돼야 안전
(예: 위키 분류페이지를 board 로 등록하려는 시도가 있다면 이 모듈은 통과시키고 일반 파이프라인이 처리).
"""
from __future__ import annotations

import re

NAME = "article_page_reject"

PATTERNS_REJECT: list[tuple] = [
    # Wikipedia (모든 lang) — `/wiki/<title>` 단일 article. Special:/Category:/Portal:/Help:/File:/Talk: 등 제외.
    # recognize_reject 자체는 negative look-ahead 로 보드 (Special:RecentChanges 등) 통과시키지만,
    # learned_blacklist 의 `_extract_url_pattern` 은 첫 path segment 만 봐서 `/wiki` 한 자리로 학습 →
    # 보드 URL (`/wiki/Special:*`) 까지 url_gate 단에서 차단됨 (nature/iln-ieee/jobplanet 와 같은 케이스).
    # → skip_learn=True. recognize_reject 는 article 만 막고, learned_blacklist 학습은 X.
    (re.compile(
        r"^https?://[a-z]{2,3}\.wikipedia\.org/wiki/"
        # 보드/메타 페이지 — namespace prefix 또는 main page title 은 제외.
        # 영어 외 lang Wikipedia 의 Special: 별명 (ko `특수:`, ja `特別:`, zh `特别:`/`特別:`) 도
        # negative look-ahead 에 박음. URL-encoded 형 (`%ED%8A%B9%EC%88%98`/`%E7%89%B9%E5%88%A5`/...)도 같이.
        # main page (각 lang): en `Main_Page`, ko `대문`/URL-encoded `%EB%8C%80%EB%AC%B8`,
        # ja `メインページ`/URL-encoded `%E3%83%A1%E3%82%A4%E3%83%B3%E3%83%9A%E3%83%BC%E3%82%B8`.
        # 기존 `특수기능:` 은 *오타* — 한국어 Wikipedia 의 Special namespace 는 `특수:` (이전 룰 보존 위해 유지).
        # 유럽어 lang Wikipedia 의 Special namespace 별명 (de `Spezial:`, fr `Spécial:`/URL-encoded
        # `Sp%C3%A9cial:`, es·pt `Especial:`, it `Speciale:`, nl `Speciaal:`, pl `Specjalna:`) 도 박음 —
        # 안 박으면 `Spezial:Letzte_Änderungen`(RecentChanges) 류가 단일 article 로 false-reject (2026-05-20-b batch).
        r"(?!"
        r"Special:|Category:|Portal:|Help:|File:|Talk:|User:|Wikipedia:|Template:|"
        r"특수:|특수기능:|분류:|위키백과:|"
        r"特別:|特别:|分类:|分類:|"
        r"Spezial:|Spécial:|Sp%C3%A9cial:|Especial:|Speciale:|Speciaal:|Specjalna:|"
        r"Main_Page|대문|%EB%8C%80%EB%AC%B8|메인_화면|메인페이지|메인_페이지|"
        r"メインページ|%E3%83%A1%E3%82%A4%E3%83%B3%E3%83%9A%E3%83%BC%E3%82%B8|"
        r"%ED%8A%B9%EC%88%98|%E7%89%B9%E5%88%A5|%E7%89%B9%E5%88%AB"
        r")"
        r"[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "위키피디아 단일 article — 게시판 아님. 폴링 대상 X (한 글 안의 참고 링크를 새 글로 감시할 수 없음). 보드는 `/wiki/Special:RecentChanges` 등.",
        True),
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
    # 인덱스 `/content/<lang>` (예: `/content/en`) 은 같은 첫 segment `/content` 공유 → skip_learn=True.
    (re.compile(
        r"^https?://encyclopedia\.ushmm\.org/content/[a-z]+/article/[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "USHMM Encyclopedia 단일 article — 게시판 아님. 폴링 대상 X. 인덱스 `/content/<lang>` 은 별도.",
        True),
    # Nature — `/articles/<doi-like-id>` 단일 article. 보드(`/articles?type=news`)와 같은 첫 segment 공유 → skip_learn=True.
    (re.compile(
        r"^https?://www\.nature\.com/articles/[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "nature.com 단일 article (`/articles/<doi>`) — 게시판 아님. 보드는 `/news`, `/research-articles`, `/subjects/<topic>`, `/articles?type=...` (쿼리 있음) 등.",
        True),
    # IEEE Innovation Learning Network — `/Public/ContentDetails.aspx?id=<GUID>` 단일 콘텐츠 상세.
    # 보드(예: `/Public/Catalog.aspx`, `/Public/trainingcatalog.aspx`)와 같은 첫 segment `/Public` 공유 → skip_learn=True.
    (re.compile(
        r"^https?://iln\.ieee\.org/Public/ContentDetails\.aspx\?", re.I,
    ), "iln.ieee.org 단일 콘텐츠 상세(`/Public/ContentDetails.aspx?id=...`) — 게시판 아님. 보드 URL (e.g. `/Public/trainingcatalog.aspx`) 을 줄 것.",
        True),
    # Jobplanet — `/contents/news-<N>` 단일 뉴스 기사. 보드(`/contents/news`)와 같은 첫 segment `/contents` 공유 → skip_learn=True.
    (re.compile(
        r"^https?://www\.jobplanet\.co\.kr/contents/news-\d+/?(?:[?#].*)?$", re.I,
    ), "jobplanet.co.kr 단일 뉴스 기사(`/contents/news-<N>`) — 게시판 아님. 보드는 `/contents/news` (트레일링 슬러그 없음).",
        True),
    # MDN docs reference — `/<lang>/docs/<path>` 모든 docs 페이지.
    # 호스트 전체가 reference docs (article-only). MDN Blog `/<lang>/blog/` 는 다른 path-prefix → 영향 X.
    # skip_learn=False (host_path_prefix=`/<lang>` 학습은 위험 — 첫 segment 가 lang 이라 너무 광범위).
    # 그러나 학습은 `_extract_url_pattern` 의 첫 path-segment 만 봄 — `/ko`, `/en-US` 같은 lang 이 path_prefix. 다른 path 영향 X 사실상.
    # 보수적으로 skip_learn=True (MDN Blog 미래 등록 막지 않기).
    (re.compile(
        r"^https?://developer\.mozilla\.org/[a-z]{2,5}(?:-[a-z]{2,5})?/docs/", re.I,
    ), "MDN docs reference 단일 페이지 — 게시판 아님. 폴링 대상 X (페이지 안 사이드바 element nav 가 board 가 아님). MDN Blog `/<lang>/blog/` 는 별도.",
        True),
    # GitHub Wiki 미러 — `/m/<user>/<repo>/wiki/<title>` 단일 wiki 페이지.
    # 호스트 전체가 wiki 미러 (article-only) — skip_learn=False.
    (re.compile(
        r"^https?://github-wiki-see\.page/m/[^/]+/[^/]+/wiki/", re.I,
    ), "github-wiki-see.page wiki 미러 단일 페이지 — 게시판 아님. 폴링 대상 X."),
    # KT용어집 — `/test/view/...` 단일 용어 entry. 호스트 전체가 용어집(백과형 article-only).
    # skip_learn=False (host_path_prefix=`/test` 차단 OK — 모두 article).
    (re.compile(
        r"^https?://www\.ktword\.co\.kr/test/view/", re.I,
    ), "ktword 용어집 단일 entry — 게시판 아님. 백과형 사이트, 폴링 대상 X."),
    # OpenAI 블로그 글 — `/index/<slug>/` 단일 article. 보드는 `/news/` (Cloudflare 차단 — 자동 등록 불가).
    # 보드/article 첫 segment 다름 (`/news` vs `/index`) → skip_learn=False 안전.
    (re.compile(
        r"^https?://openai\.com/index/[^/?#]+/?(?:[?#].*)?$", re.I,
    ), "openai.com 단일 글페이지 (`/index/<slug>/`) — 게시판 아님. 보드 `/news/` 는 Cloudflare 차단 (자동 등록 불가)."),
    # SUMO docs (DLR Eclipse SUMO documentation) — mkdocs/material-style static docs.
    # `/docs/<name>.html` 단일 docs 페이지. probe `first_article_url` 가 `<input>#<anchor>` (same-page section)
    # 라 nav-only/meta-diverging 게이트가 못 잡음 — 명시 호스트 패턴이 효율적.
    # host 의 다른 path (`/wiki/`, `/`, release notes 등) 가능성 → skip_learn=False 안전 (path_prefix=`/docs` 만 차단).
    (re.compile(
        r"^https?://sumo\.dlr\.de/docs/", re.I,
    ), "sumo.dlr.de/docs 단일 문서 페이지 — 게시판 아님. mkdocs-style 정적 문서, 새 글 발행 X (폴링 의미 없음)."),
    # Tistory 메인 — `www.tistory.com/` 멀티-블로그 인기글 hub. row URL 들이 *서로 다른 서브도메인*.
    # 개별 블로그 (`<subdomain>.tistory.com/...`) 는 별도 host 라 영향 X.
    # skip_learn=True — host=`www.tistory.com` path=`` 학습은 모든 path 차단 (보드 없는 hub 라 안전이지만 보수적).
    (re.compile(
        r"^https?://(?:www\.)?tistory\.com/?(?:\?.*)?(?:#.*)?$", re.I,
    ),
        "tistory.com 메인 — 여러 블로그 인기글 hub. 게시판 아님 (개별 블로그 `<subdomain>.tistory.com/...` 은 따로 등록).",
        True),
]
