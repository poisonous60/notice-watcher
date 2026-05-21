---
slug: host_sigmod-org_root_486a8db8
url: https://sigmod.org/
status: 🧩 수동 config — WordPress RSS feed 로 baseline 가능
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, sigmod, wordpress, rss-fallback]
requested_by: batch
---

## 무엇이 일어났나

사용자 전달 기준 batch `gen_fail(rc=1)` 이며 마지막 실패 키는 `[FAIL] posts_nonempty` 계열이다.
로컬 worktree에는 `output/poll_state/host_sigmod-org_root_486a8db8.FAILED.json` 와
`output/probe/host_sigmod-org_root_486a8db8/` 가 없어 `triage.py show` 의 `last_feedback`/`diagnosis`
원문은 재인용하지 못했다.

직접 확인 결과 `https://sigmod.org/feed/` 는 WordPress RSS 로 200 응답, `channel > item` 10건을 제공한다.
샘플은 `Database Researchers Named ACM Fellows 2025`, link `https://sigmod.org/acm-fellows-2025/`,
guid `https://sigmod.org/?p=5305`, pubDate `Mon, 16 Feb 2026 04:50:26 +0000` 이다.

## 픽스

`configs/host_sigmod-org_root_486a8db8.json` 생성. `strategy=httpx_html`, `row_selector=channel > item`,
`post_id=guid ?p=<id>`, `title/link/pubDate/description` 을 사용한다. SIGMOD feed 가 한 번 503을 반환해
config timeout 은 40초로 두었다.

## Track B 검토

- **2a 인식기 — X.** 단일 WordPress 사이트 RSS rescue 이며 이번 HARD-STOP은 engine/recognizers 변경을 금지한다.
- **2b article-url — X.** 첫 글 오인보다 목록 소스 선택 문제다.
- **2c/2d probe/generate — 보류.** `posts_nonempty` 누적 query 는 57건이고 `track_b_trigger=true` 이지만,
  이번 지시는 config/case allow-list 밖인 probe/generate/prompt 수정을 금지했다.
- **2e 수동 config — O.** 기존 `httpx_html` XML 파서와 RSS 선례로 해결된다.

일반화 안 되는 이유: WordPress RSS 자동 발견은 유효한 Track B 후보지만 allow-list 밖 코드 변경 없이는 이번
작업에서 적용할 수 없다.

## 회귀 검증

- `preflight: miss — host_sigmod-org_root_486a8db8` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 5건, first post `5305`.
- 첫 글 `fetch_article()` body length 1387.

