---
slug: host_yo-star-com_news_8f81136f
url: https://www.yo-star.com/news/
status: 🚫 REJECTED — agent self-veto(non_board)
outcome: rejected
date: 2026-05-27
failure_keys: [gen_fail, non_board_self_veto, spa_shell, host_mismatch]
fix_layer: none
config_strategy: n/a
adapters_changed: []
engine_files_touched: []
tags: [games-mobile-batch, yo-star, spa-shell, hr-aggregator, codex-agentic-self-veto]
requested_by: 2026-05-24-games-mobile-batch-retry
---

## 조사 결과

probe: 정적 HTML 661 bytes SPA shell (Vite/Vue, `<div id="app"></div>`, `main-*.js` 로 frontend render). server=istio-envoy.

batch retry 시 N100 Chromium `ERR_NAME_NOT_RESOLVED` (OS-level `getent hosts` + curl 200 정상 — Chromium DNS resolver flake) → `gen_fail`.

dev box `register.py --reuse-probe` 1회: probe artifact reuse → agent api_loop hard fail (`host='app.mokahr.com' ≠ list host='www.yo-star.com' — 검색결과/aggregator 가능성, article body 통합 추출 X`) → escalate to agentic codex → **agent self-veto `non_board`** (rc=3) → `_save_rejected` 자동 호출.

진짜 `/news/` 콘텐츠는 mokahr (HR 채용 aggregator) 으로 click-through. 게시판 X.

## 처리

- dev + N100 `.REJECTED.json` 박힘 (agent self-veto reason)
- jobs row latest status='rejected' update
- 종료 자리 = REJECTED (자동 처리)

## 후보 (deferred)

`_deferred_heuristics.md` 의 `spa_shell_with_hr_aggregator_detail_click` — SPA shell + detail click host ≠ list host = aggregator 패턴. catalog 1건이라 보류.
