---
slug: host_viz-com_blog_372c6f29
url: https://www.viz.com/blog
status: 🔧 손 config (작동중, baseline 2, httpx_html)
outcome: improved
date: 2026-05-21
requested_by: batch
failure_keys: [article_body_len, headless_429_static_ok]
fix_layer: C+config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [scripts/probe.py]
tags: [viz, blog, static-ok, headless-429]
---

## 무엇이 일어났나
`/watch https://www.viz.com/blog` batch gen_fail. 마지막 실패는 `[FAIL] article_body_len: post_id=mangaka-musings-05-17-2026 0자 (<100 — content selector 의심)`.

probe 결과는 `S1.H2`/`S1.H3`/`S1.H4` 정적 HTTP가 200 OK였지만, headless `S4`가 `429 Too Many Requests` JSON을 받아 `list.html`에 저장했다. `scripts/probe.py`가 headless body를 classification 확인 없이 우선 사용해 `html_repeating_patterns=0`이 되었고, 생성기는 정상 정적 HTML의 `#posts_wrapper` row와 글 본문 selector를 안정적으로 못 잡았다.

## 무엇을 바꿨나
**Track B (C)**: `scripts/probe.py`에서 Phase 7 후보 추출 입력을 고를 때 headless 결과가 `Classification.OK`인 경우에만 headless HTML을 사용하게 했다. headless가 429/blocked이면 이미 성공한 static HTML로 fallback한다.

**단일 config**: `configs/host_viz-com_blog_372c6f29.json`
- 목록: `#posts_wrapper > article` 중 `/blog/posts/` 링크가 있는 row만 수집
- 본문: `#post_row .context-copy`
- 날짜/작성자: 글 페이지 header에서 enrich

## 일반화 효과
정적 HTTP는 정상인데 headless만 429/blocked인 사이트에서 probe 후보가 빈 값으로 퇴행하는 것을 막는다. 자동 솔버가 정상 static HTML의 반복 row를 보게 되므로 같은 패턴의 `posts_nonempty`/`article_body_len` 실패를 줄일 수 있다.

## 검증
- `python scripts/register.py --config configs/host_viz-com_blog_372c6f29.json` → PASS, baseline 2건, `.FAILED.json` 정리됨.
- make_adapter 직접 스모크 → posts 2건, 본문 길이 7227/5781자, published_at/author enrich 정상.
- `python scripts/probe.py "https://www.viz.com/blog" --lite` → headless `S4`는 429지만 Phase 7이 static OK HTML로 fallback해 HTML 반복 패턴 15건, 본문 진입 OK.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 1035 / FAIL 0 / WARN 0.
