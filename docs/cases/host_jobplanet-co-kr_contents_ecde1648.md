---
slug: host_jobplanet-co-kr_contents_ecde1648
url: https://www.jobplanet.co.kr/contents/news-616
status: ❌ 거부 (단일 뉴스 기사 URL — 게시판 아님). 인식기 fast-path skip_learn=True.
outcome: rejected_with_policy
date: 2026-05-16
fix_layer: F
failure_keys: [single_article_page, article_body_len_zero, spa_cloudflare, diverging_first_article]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, engine/recognizers/__init__.py, scripts/register.py]
tags: [single-article-reject, recognizer-fast-path, skip-learn, jobplanet, spa-cloudflare]
requested_by: poi23619 (preview)
---

## 사용자 의도

사용자가 `jobplanet.co.kr/contents/news-616` 을 `/preview` 로 등록 시도. URL 의 `news-<N>` 패턴이 단일 뉴스 기사를 가리킴. 보드는 `/contents/news` (트레일링 슬러그 없음).

## probe + LLM 처리 흔적 (FAILED.json)

- `last_feedback: [FAIL] article_body_len: post_id=8141 0자 (<100 — content selector 의심)`
- LLM 이 보드 URL `/contents/news` 으로 *교정* → 목록 추출 *성공* (5건: news-8141/8135/8120/8177/8201).
- 본문 selector `div.jplyst_body` 가 실제로 0자 — 본문 페이지는 Next.js SPA + Cloudflare anti-bot (`S1.Hcap 403 Attention Required`) 라 static HTTP 가 본문 못 받음.
- `[warn] matches_probe_first_article: probe first_article_url='https://www.jobplanet.co.kr/companies/38274' 와 일치하는 글 URL 없음` — probe 가 first_article 로 *회사 프로필* 페이지 잡음 (전혀 다른 섹션).

## 진단 — 단일 article + 본문 SPA-only 이중 문제

1. **input 이 단일 article URL**: `news-616` 은 한 기사. 폴링 가치 X.
2. **본문 SPA 전용**: `/contents/news-<N>` 페이지는 Next.js 가 client-render. static HTTP 로 본문 못 받음. playwright_html 어댑터 + Cloudflare 우회 필요.

설사 보드 URL `/contents/news` 로 hand-config 작성해도 본문 fetch 가 막힘 — 본격적인 손-config 또는 손어댑터 필요. 사용자 입력이 article URL 인 것 + 본문 어려움 결합 → **REJECT** 가 적정 (사용자가 *진짜 보드 URL* 을 줘도 추가 작업 필요할 것이지만, 그건 그때 별도로).

## 픽스 (fix_layer: F)

`engine/recognizers/article_page_reject.py` 에 jobplanet 패턴 추가:
```python
(re.compile(r"^https?://www\.jobplanet\.co\.kr/contents/news-\d+/?(?:[?#].*)?$", re.I),
 "jobplanet.co.kr 단일 뉴스 기사(`/contents/news-<N>`) — 게시판 아님. 보드는 `/contents/news` (트레일링 슬러그 없음).",
 True)  # skip_learn=True
```

`skip_learn=True` 이유: 보드 URL `/contents/news` 가 같은 첫 path-segment `/contents` 공유 → `learned_blacklist` path_prefix 차단이 보드까지 막을 수 있음. REJECTED 마커만 박음.

## 트랙 B 후보 — 검토

- **2a (인식기)**: ✅ jobplanet 패턴 추가.
- **2b (--article-url)**: ❌ input 자체가 article URL. 더 골치아픈 건 보드 URL `/contents/news` 로 register 해도 본문 SPA + Cloudflare 때문에 막힘.
- **2c (probe heuristic)**: ❌ jobplanet 페이지에는 og:type / schema.org 명시 신호 없음. SPA 페이지가 client-render 라 server HTML 에 meta 없음. 다른 heuristic 후보 (URL shape `<board>-<id>` 패턴 검출) 는 일반화 어려움 — *board-name-<id>* 형식은 게시판에서 매우 흔함 (board ID 도 같은 형식 사용).
- **2d (probe artifact)**: ❌ artifact 정상.

→ 결론: 인식기 fast-path 만.

## 사용자 후속

`/watch https://www.jobplanet.co.kr/contents/news` 시도 가능 — 하지만 본문 추출이 어렵다는 것을 알림. 진짜 등록하려면 손-config (playwright_html + Cloudflare 우회) 별도 작업 필요.
