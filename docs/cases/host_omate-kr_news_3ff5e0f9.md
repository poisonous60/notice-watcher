---
slug: host_omate-kr_news_3ff5e0f9
url: https://www.omate.kr/news/articleView.html?idxno=21030
status: 🔧 손 config (httpx_html, baseline 20건) — 사용자가 articleView(개별 기사) URL 줌, articleList 로 변환
outcome: handcrafted
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty, list_url_none, candidates_zero]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [omate, articleView-given, articleList-handwritten, korean-local-news]
---

## 무엇이 일어났나
사용자가 `https://www.omate.kr/news/articleView.html?idxno=21030` (개별 기사 URL — i-news 시스템) `/preview`. probe 가 글페이지만 fetch → `list_url=None`, `candidates=0`, `first_article_url='.../articleView.html?idxno=54576'` (해당 글 페이지 안의 관련 기사 링크). 자동 파이프는 list URL 못 잡고 4회 retry 실패 — `[FAIL] posts_nonempty: 0건`.

자동 last_config 가 추측한 `articleList.html?view_type=sm` + `div.article-list-content > ul > li` selector — list URL 은 맞지만 selector 가 *그 사이트* 의 실제 구조와 불일치. 실측 selector = `section#section-list > ul > li`.

## 무엇을 바꿨나 (fix layer: none — 단발 손-config)
**`configs/host_omate-kr_news_3ff5e0f9.json`** — httpx_html. slug 는 원 FAILED 와 동일 유지 (`_source_url` 도 사용자가 준 articleView URL). `list.url_template` 만 articleList.html?view_type=sm 으로 박음.
- `row_selector`: `section#section-list > ul > li`
- `row_required_selector`: `h2.titles > a`
- `post_id`: href 의 `idxno=(\d+)` 추출
- `title`: `h2.titles > a` 텍스트
- `url`: href urljoin
- `author`: `div.byline div.name`
- `published_at`: 생략 (목록 `dated` 가 `MM-DD HH:MM` 연도 모호 — post_id 중복 기반 신규 판정으로 충분)
- `article.content`: `article#article-view-content-div` (body 4621 chars OK)
- `polite_sleep`: 5~10s (작은 지역 언론, 보수치)

## 회귀 검증
- 스키마 OK, 스모크: list 5건, body 4621 chars.
- `register.py --config` → baseline 20건, FAILED.json + triage_queue 자동 정리.

## 일반화 안 함 이유
omate.kr 은 i-news (한국 지역신문 다수가 같은 솔루션) 인데 selector 형태(`section#section-list`)가 i-news 표준이라기보단 omate 의 커스텀 테마. 같은 패턴 추가 2건 이상 들어오면 그때 `i-news` 인식기 검토. 1건만으론 over-generalization 위험.

## 후속 후보 (다른 case 와 공유)
- **트랙 B-2c**: probe digest 에 `is_article_page_url` 휴리스틱 (list_url=None & candidates=0 & first_article_url 가 user-given URL 과 같은 path pattern). 알려지지 않은 호스트 의 article URL 케이스 — preflight 가 LLM 호출 4회 비용 없이 즉시 사용자에게 "list URL 줘" 안내 가능. naver-blog 처럼 자동 변환 가능한 플랫폼 외엔 모두 이 휴리스틱이 빠른 fail-fast.
