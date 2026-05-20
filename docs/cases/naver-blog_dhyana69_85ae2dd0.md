---
slug: naver-blog_dhyana69_85ae2dd0
url: https://m.blog.naver.com/PostView.nhn?blogId=dhyana69&logNo=150071320787&proxyReferer=https:%2F%2Fwww.google.co.kr%2F
status: ✅ 자동 (recognizer 신규 — naver-blog 플랫폼 인식, NaverBlogRssAdapter 가 RSS 피드 직접 파싱)
outcome: handcrafted
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty, list_url_none, candidates_zero]
fix_layer: F
config_strategy: handwritten
adapters_changed: [naver_blog]
engine_files_touched: [adapters/naver_blog.py, adapters/__init__.py, engine/recognizers/naver_blog.py]
tags: [naver-blog, rss-feed, known-platform-recognizer, article-url-given]
---

## 무엇이 일어났나
사용자가 `m.blog.naver.com/PostView.nhn?blogId=dhyana69&logNo=...` (개별 글 URL) 을 `/preview`. 자동 파이프 4회 retry 실패 — `[FAIL] posts_nonempty: 0건`. probe 산출물: `list_url=None`, `candidates=0`, `first_article_url='https://m.blog.naver.com/CheckIn.naver'` (사이드바 링크). last_config 가 추측한 `m.blog.naver.com/PostList.naver?blogId={board}` 의 `div.post_tit_area` selector — 그 페이지가 React SPA 라 정적 HTML 에 글 행 0개. probe 가 list 페이지 자체를 fetch 안 했고, 사용자가 글 URL 줘서 자동 디스커버리 불가.

## 무엇을 바꿨나 (fix layer: F — 신규 어댑터 + 인식기)
- **`adapters/naver_blog.py`** — `NaverBlogRssAdapter` 신규. `rss.blog.naver.com/<blogId>.xml` 직접 파싱 (BeautifulSoup `xml` parser, lxml). 50개까지 안정 — RSS 가 데스크톱 iframe·모바일 SPA 우회. 본문은 `m.blog.naver.com/PostView.naver` 의 `div.se-main-container`(SE ONE) / `div#postViewArea`(legacy SE) 추출.
- **`engine/recognizers/naver_blog.py`** — `naver-blog` 인식기. PATTERNS 4종:
  - `PostView.{naver,nhn}` / `PostList.naver` 쿼리에서 `blogId`
  - `/<blogId>/<logNo>` path 에서 blogId (개별 글)
  - `/<blogId>` 단독 path (블로그 홈)
  - `_RESERVED` set 으로 `Recommendation.naver` 등 페이지 이름이 blogId 로 잡히는 거 방지
- **`adapters/__init__.py`** — `NaverBlogRssAdapter` export.
- 등록 baseline 30건 (`naver-blog_dhyana69_85ae2dd0`, hash 는 원 FAILED 와 같으나 platform prefix `host_blog-naver-com` → `naver-blog` 로 바뀜 → 옛 FAILED.json + triage_queue 항목은 손으로 정리).

## 회귀 검증
- `register.py "<URL>"` → recognize hit, baseline 30건, body 추출 OK (3140 chars 샘플).
- `recognize('https://blog.naver.com/dhyana69')` (홈), `recognize('.../PostList.naver?blogId=dhyana69')` (legacy list) 모두 같은 config 반환 — 같은 slug 로 자동 통합.
- (트랙 B 검토) 같은 PR 의 `naver-blog_ghangth_5a895e5f` 가 즉시 풀림 — 새 사용자 누군가 네이버 블로그 `/preview` 하면 모두 자동.

## 후속 후보
- **트랙 B-2c (다음 PR)**: probe digest 에 `is_article_page_url` 휴리스틱 신호 (list_url=None & candidates=0 & first_article_url ≈ user-given URL). 알려지지 않은 호스트의 article URL 케이스 (omate/wiki/terms) preflight 거부 또는 LLM 힌트.
