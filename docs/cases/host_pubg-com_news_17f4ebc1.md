---
slug: host_pubg-com_news_17f4ebc1
url: https://pubg.com/news/
status: "✅ improved — static placeholder no longer accepted as static row evidence"
outcome: improved
date: 2026-05-28
fix_layer: C
failure_keys: [fetch_list_0_url_mismatch, probe_grounding_article_content_selector]
config_strategy: auto
engine_files_touched: [probe/diagnose.py]
tags: [cross-site, spa, locale-redirect, static-evidence]
---

## 무엇이 일어났나

`https://pubg.com/news/` 는 `/en/news` 로 redirect 되고, static fetch에는 `post-contents__card` placeholder가 반복되지만 `/en/news/<id>` article href가 없다. rendered Playwright payload에는 article URL이 있으므로, 기존 `_static_row_evidence` 가 `list_payload.first_article_url` fallback으로 static evidence를 만든 뒤 "정적 HTTP 충분" 쪽으로 기울 수 있었다.

실제 fail signal:
- `[FAIL] fetch_list 0건; url mismatch /en/news/`
- `probe_grounding_article_content_selector: main matched 0`

## 픽스

`probe/diagnose.py:_static_row_evidence` 가 static-like `body_path` HTML 안에서 pattern selector를 직접 select하고, 해당 static node 내부에서 non-JS article href를 찾을 때만 static evidence를 인정한다. static placeholder만 있으면 evidence를 만들지 않으므로 SPA/hydration 판단이 살아난다.

## 6-layer audit

- E schema: miss — config validation 전 probe verdict 입력 문제다.
- D retry feedback: miss — retry feedback은 이미 실행 실패 뒤에만 작동한다.
- C probe heuristic: hit — static-vs-SPA evidence acceptance를 고쳤다.
- B few-shot: miss — 예제 config로 placeholder evidence 오인을 막을 수 없다.
- A system prompt: miss — LLM 지시 이전의 probe digest 근거 문제다.
- F engine/recognizer: miss — Krafton/PUBG 단일 board로 recognizer 일반화 근거가 약하다.

## 회귀 검증

- `tests/probe_heuristics/test_static_row_evidence.py`
  - static placeholder 17개 + rendered `first_article_url` fallback fixture가 수정 전 실패, 수정 후 PASS.
  - static body에 실제 article href가 있는 SSR fixture는 계속 evidence를 인정.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → exit 0, `PASS 1790 FAIL 0 WARN 1 SKIP 0`.

## probe artifact 확인

`output/probe/host_pubg-com_news_17f4ebc1/` 는 이 worktree에 없어 artifact replay는 수행하지 못했다. fixture가 동일 failure mode를 고정한다.
