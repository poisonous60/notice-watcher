---
slug: _generic_c-layer_verdict_hydration_2026-05-28
url: N/A
status: "✅ improved — static hydration placeholder downgrades static HTTP verdict"
outcome: improved
fix_layer: C
failure_keys: [fetch_list_0_url_mismatch, posts_nonempty, list_url_mismatch]
tags: [cross-site, spa, hydration, verdict-downgrade]
date: 2026-05-28
engine_files_touched: [probe/diagnose.py, scripts/register.py]
---

# Generic C-layer Verdict Hydration Downgrade

## 무엇이 일어났나

`https://pubg.com/news/` 는 `/en/news` 로 redirect 되고, 정적 HTML에는 `post-contents__card` placeholder가 반복되지만 실제 article href (`/en/news/<id>`)가 없다. Playwright-rendered `list.html`에는 10개 카드와 10개 href가 있으므로 목록은 JS hydration 뒤에 완성된다.

이전 Fix B는 `_static_row_evidence=None` 까지는 만들었지만, verdict flow는 `static_ok`를 계속 살려 두었다. 그 결과 probe verdict가 `정적 HTTP로 충분`으로 남고, agentic 생성은 `httpx_html` 방향으로 `0 posts; list URL mismatch`를 반복했다.

## 무엇을 바꿨나

- `probe/diagnose.py`
  - `STATIC_INSUFFICIENT_HYDRATION_PREFIX`를 추가했다.
  - `list_payload.first_article_url`가 있고, static-like body의 anchor href에서 같은 article path를 찾을 수 없고, static body에는 반복 selector가 존재하면 hydration placeholder로 본다.
  - 이 경우 `static_ok=[]`, `captured_ok=False`로 낮춰 verdict/recommended strategy가 Playwright 방향으로 가게 한다.
  - `static_vs_headless` 내부 dict에는 `trigger_rule=hydration_placeholder`, `placeholder_selector`, `missing_article_url`을 붙인다.
- `scripts/register.py`
  - 새 hydration prefix를 기존 static insufficient feedback 경로에 태워 `strategy=playwright_html + list.wait_selector` 힌트를 계속 받게 했다.

## Track B 6-layer audit

- E schema: miss — config validation 전 probe verdict 입력 문제다.
- D retry feedback: miss — retry feedback은 생성 후보 실패 뒤에만 작동하고, 이번 문제는 첫 방향 선택 근거가 잘못된 것이다.
- C probe digest 신호: hit — static body와 rendered payload의 article href 존재 차이를 probe verdict에서 반영한다.
- B few-shot: miss — 예제 config로 정적 placeholder와 hydration 목록을 안정적으로 구분할 수 없다.
- A system prompt: miss — prompt 이전의 `diagnosis.verdict`와 escalation hint가 잘못된 방향을 준다.
- F engine/recognizer: miss — PUBG 전용 recognizer나 runtime 변경 없이 probe 판정만으로 일반화 가능하다.

## 회귀 검증

- RED: `python scripts/probe_smoke.py --stage 5 --verbose`
  - `test_verdict_hydration_downgrade:hydration_placeholder_downgrades_static_verdict` 실패: `verdict='정적 HTTP로 충분'`
  - `test_verdict_hydration_downgrade:hydration_placeholder_note_uses_stable_prefix` 실패
  - `test_verdict_hydration_downgrade:hydration_placeholder_recommends_playwright` 실패: `recommended='httpx (S1.H2)'`
- GREEN: `python scripts/probe_smoke.py --stage 5 --verbose` -> exit 0, `143 파일 · 1488 케이스 · 0 FAIL · coverage 49/49`.

## probe artifact 확인

`output/probe/host_pubg-com_news_17f4ebc1/` 는 이 worktree에 없어 real artifact replay를 수행하지 못했다. 이번 case는 fixture로 동일 failure mode를 고정한다.

## 영향 범위

정적 HTML에 반복 row selector가 있지만 article href가 없고, rendered payload에는 첫 글 URL이 있는 SPA hydration placeholder 계열에만 강하게 작동한다. 정적 body에 같은 article href가 있는 SSR fixture는 계속 `정적 HTTP로 충분` verdict를 유지한다. `size` trigger와 `repeat` trigger의 기존 의미는 바꾸지 않았다.

`docs/cases/INDEX.md` 와 `output/cases.sqlite3` 는 이 Codex handoff의 hard-stop 지시에 따라 갱신하지 않았다.
