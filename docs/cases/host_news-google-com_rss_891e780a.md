---
slug: host_news-google-com_rss_891e780a
url: https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko
status: ✅ 인식기 확장 (Google News top-stories/topic/section 피드 자동 등록)
outcome: handcrafted
date: 2026-05-20
fix_layer: F
failure_keys: [post_id_stable_shape, known_platform_partial]
config_strategy: handwritten
adapters_changed: [GoogleNewsRssAdapter]
engine_files_touched: [engine/recognizers/google_news.py, adapters/google_news_rss.py]
tags: [recognizer, google, news, rss, platform-generalization, batch-2026-05-20-b]
requested_by: catalog 2026-05-20-b
---

## 무엇이 일어났나

batch 2026-05-20-b 의 Google News 메인 RSS (`news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko`)
gen_fail:

> [FAIL] post_id_stable_shape: 안정적 ID 모양 아님(공백 등): ['CBMingF...(300자+)']

검색 변형 (`/rss/search?q=게임`) 은 등록 성공.

## 진단 (분기 2a 인식기 + F 어댑터)

`google_news` 인식기는 `/search` (q= 검색) 만 매칭. top-stories `news.google.com/rss` (검색 아님,
q 없음) 는 미커버 → generic httpx_html 파이프가 RSS `<item>` 파싱은 하나 **post_id = raw
Google guid (CBMi… 300자+)** → `post_id_stable_shape` 의 200자 cap 초과로 fail.

`GoogleNewsRssAdapter` 는 이미 guid 를 sha1 로 줄여 안정 post_id 화함 — 인식기가 이 URL 을
매칭만 했으면 통과했을 것. 즉 known-platform **부분 커버** 갭.

## 트랙 B (영구) = 트랙 A (즉시)

1. 어댑터: `feed_url` kwarg 모드 추가 — 직접 피드 URL (검색 아님) 을 그대로 fetch. query 필수
   완화 (`query` 또는 `feed_url` 중 하나). 기존 search config 후방호환 유지.
2. 인식기: `_FEED_RE` 추가 — top-stories(`/rss` + query/end) · topic(`/rss/topics/<id>`) ·
   section(`/rss/headlines/...`) 매칭 → `feed_url` 모드 config 발급. `/rss/search`(검색)·
   `/rss/articles/<id>`(단일 글) 는 제외.

board label: top→`top_<hl>_<gl>`, topic→`topic_<token>`, section→`<name>`.

## 회귀 검증

recognize: top-stories→feed(top_ko_KR), search→search(게임, 후방호환), topic→feed, section→
feed, `/rss/articles/`→None. live fetch_list (top-stories KR) = 10 posts, sha1 post_id 안정.
probe_smoke stage 3 50/50 (gnews search config 포함), stage 5 0 FAIL.
