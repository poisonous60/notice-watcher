---
slug: host_iln-ieee-org_Public_ff9aa2d5
url: https://iln.ieee.org/Public/ContentDetails.aspx?id=9D3FE9C6144F4C298ABDE18D84EDB93C
status: ❌ 거부 (단일 콘텐츠 상세 페이지 — 게시판 아님). 인식기 fast-path skip_learn=True.
outcome: rejected_with_policy
date: 2026-05-16
fix_layer: F
failure_keys: [single_article_page, content_detail_page, board_shape_false_positive]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, engine/recognizers/__init__.py, scripts/register.py]
tags: [single-article-reject, recognizer-fast-path, skip-learn, ieee-iln]
requested_by: poi23619 (preview)
---

## 사용자 의도

사용자가 `iln.ieee.org/Public/ContentDetails.aspx?id=<GUID>` URL 을 `/preview` 로 등록 시도. 이 URL 은 IEEE Innovation Learning Network 의 *단일 콘텐츠 상세 페이지* — `?id=<GUID>` 쿼리로 한 콘텐츠를 가리키는 article-shaped URL. 폴링 대상 게시판 아님.

## probe + LLM 처리 흔적 (FAILED.json)

- `last_feedback: [FAIL] posts_nonempty: 0건`
- LLM 이 추측한 보드 URL: `https://iln.ieee.org/public/trainingcatalog.aspx` (생성된 config 의 `list.url_template`). row 0건.
- `[warn] matches_probe_first_article: probe first_article_url='https://iln.ieee.org/public/contentdetails.aspx?id=238D136945ED4B78B33A724488204AEA' 와 일치하는 글 URL 없음` — probe 가 잡은 first_article 도 같은 ContentDetails.aspx 형식 (= 또 다른 단일 article URL).

## 진단 — 같은 URL 형식이 글 = article-shaped input

input URL: `/Public/ContentDetails.aspx?id=A`
first_article_url: `/public/contentdetails.aspx?id=B`

→ 둘 다 동일 `path + query-key` 구조. **input 도 article 페이지** (probe 가 그 페이지 안의 in-text 또는 추천 콘텐츠 링크 중 하나를 first_article 로 잡았을 뿐).

기존 `_single_article_nav_only_check` 게이트는 `outside_nav==0` 필요 — probe 결과 `in_nav=1, outside_nav=1` 이라 안 잡힘. og:type=article 도 *없음* (이 사이트는 ASP.NET 으로 메타 태그 약함) — 새 `_meta_article_diverging_check` 게이트도 안 잡힘.

따라서 *호스트 명시 fast-path* (인식기 PATTERNS_REJECT) 가 유일한 방법.

## 픽스 (fix_layer: F)

`engine/recognizers/article_page_reject.py` PATTERNS_REJECT 에 3-tuple 추가:
```python
(re.compile(r"^https?://iln\.ieee\.org/Public/ContentDetails\.aspx\?", re.I),
 "iln.ieee.org 단일 콘텐츠 상세(`/Public/ContentDetails.aspx?id=...`) — 게시판 아님. 보드 URL (e.g. `/Public/trainingcatalog.aspx`) 을 줄 것.",
 True)  # skip_learn=True
```

`skip_learn=True` 이유: `_extract_url_pattern` 이 path 의 *첫 segment* 만 추출 → `/Public`. 이걸 `learned_blacklist` 에 박으면 `/Public/Catalog.aspx`, `/Public/trainingcatalog.aspx` 등 *진짜 보드 URL* 도 path_prefix `/Public` 매칭으로 차단됨. → 학습 X, REJECTED 마커만 박음.

## 트랙 B 후보 — 검토

- **2a (인식기 PATTERNS 확장)**: ✅ 직접 수행. fast-path 거부.
- **2b (--article-url 재시도)**: ❌ input 자체가 article URL. board URL 을 알 수 없음 (LLM 시도한 `trainingcatalog.aspx` 도 0건).
- **2c (probe 휴리스틱)**: ❌ — 이 사이트는 og:type / schema.org / microdata 모두 없음. `_meta_article_diverging_check` 신호 0. 별도 휴리스틱 (URL shape similarity) 은 fixture 1건뿐 — 일반화 어렵고 ROI 낮음.
- **2d (probe artifact 수정)**: ❌ — artifact 정상.

→ 결론: 인식기 fast-path 가 적정.

## 사용자 후속

`/watch <보드 URL>` 로 재시도 권유. iln.ieee.org 의 실제 보드는 `/Public/trainingcatalog.aspx` 또는 카탈로그 페이지 — 사용자가 직접 찾아 줘야 함.

배포 후 동작:
- N100 에서 `register.py "<원본 URL>"` 실행 시 recognize_reject fast-path → REJECTED 마커 + triage_queue 정리.
- 이후 같은 URL `/preview`·`/watch` 시도는 봇이 `is_rejected(slug)=True` 로 즉시 "이전에 거부됨" 응답.
