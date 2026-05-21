---
slug: host_medium-com_airbnb-engineering_2931b5a3
url: https://medium.com/airbnb-engineering
status: ✅ 등록 완료 (Medium publication → RSS config + recognizer)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, feed_candidates]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/medium.py]
tags: [medium, rss, publication, recognizer, batch-2026-05-21-blogcms-gen3]
---

## 원인

Medium publication HTML은 정적 HTML 안에 글 링크가 보이지만 class 기반 selector가 불안정하고 자동 생성은 `[FAIL] posts_nonempty: 0건`을 반복했다. 페이지에는 `rel="alternate" type="application/rss+xml"`로 `https://medium.com/feed/airbnb-engineering`이 노출되어 있었다.

## 처리

- `configs/host_medium-com_airbnb-engineering_2931b5a3.json` 추가: publication RSS `https://medium.com/feed/airbnb-engineering`을 `channel > item`으로 추출한다.
- Medium recognizer가 `https://medium.com/airbnb-engineering` 입력을 같은 RSS config로 빌드한다.
- slug 보존 확인: `url_to_slug("https://medium.com/airbnb-engineering")` → `host_medium-com_airbnb-engineering_2931b5a3`.

## 회귀 검증

- `python scripts/register.py --config configs/host_medium-com_airbnb-engineering_2931b5a3.json` → PASS, baseline 10건.
- `python scripts/register.py "https://medium.com/airbnb-engineering" --force` → recognizer hit, baseline 10건.
- `python tests/recognizers/test_medium.py` → PASS.

## 트랙 B

Publication URL과 `/feed/<publication>` URL을 모두 recognizer에 넣었다. 단일 글 URL(`/p/<id>`)과 user profile URL(`@alice`)은 negative test로 배제했다.
