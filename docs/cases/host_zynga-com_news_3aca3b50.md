---
slug: host_zynga-com_news_3aca3b50
url: https://www.zynga.com/news/
status: 🚫 REJECTED — capability_blocked (WP API + browser anti-bot)
outcome: rejected
date: 2026-05-27
failure_keys: [gen_fail, capability_blocked, wordpress_api_502, anti_bot]
fix_layer: none
config_strategy: n/a
adapters_changed: []
engine_files_touched: []
tags: [games-mobile-batch, zynga, wordpress, anti-bot, wp-recognizer-fallback]
requested_by: 2026-05-24-games-mobile-batch-retry
---

## 조사 결과

probe `list_candidates.json` 의 `wordpress_platform`:
- `is_wordpress: true`
- `api_base: https://www.zynga.com/wp-json`
- `posts_endpoint: https://www.zynga.com/wp-json/wp/v2/posts`

`scripts/register.py:2891-2904` 의 WP recognizer dispatch 가 작동:
```
[PHASE] wordpress_detect
[register] 🔎 WordPress REST marker 검출 — wp/v2/posts config 등록 시도
[register] 알려진 플랫폼(wordpress) fetch_list 실패 — HTTPStatusError("Server error '502 Bad Gateway' for url 'https://www.zynga.com/wp-json/wp/v2/posts?_embed=&page=1&per_page=30'")
[register] WordPress REST 폴백 (API 빈/차단/검증 실패) — 일반 파이프라인 계속.
```

폴백 후 분류기는 board 인정 (`conf=0.97 새 글을 폴링하는 index`). probe 가 첫 글 = `/games/101-okey-plus/` (game page) 잘못 picked → preflight reprobe → article CSS selector 0 nodes → gemini api_loop hard fail → agentic max_cycles fail.

live curl 결과:
- `/news/` 200 (curl default UA, Linux)
- `/wp-json/wp/v2/posts?per_page=3` **502 Bad Gateway**
- `/wp-json` **timeout (15s)**
- user browser `/news/` **502 Bad Gateway**

→ WordPress 게시판 *맞음* 이지만 (1) WP REST API endpoint 영구 anti-bot 차단 (2) HTML 프론트엔드도 region/UA 별 차단. N100 polling 도 같은 502 → 등록해도 즉시 fail. cap_blocked 영구.

## 처리

- dev + N100 `.REJECTED.json` 박힘 (capability_blocked reason)
- jobs row latest status='rejected' update
- 종료 자리 = REJECTED 손-박기 (cap_blocked 영구)

## 후보 (deferred)

`_deferred_heuristics.md` 의 `wp_recognizer_502_immediate_cap_blocked` — WP recognizer dispatch 가 502/timeout 만나면 폴백 X, 즉시 cap_blocked REJECTED 자동 박기 (agentic generate 호출 낭비 방지). cohort 1건이라 보류.
