---
slug: _generic_probe_verdict_soft404_and_static_rows
url: (generic)
status: "probe verdict soft-404/static-row 판정 2종 개선"
outcome: improved
fix_layer: C
failure_keys: [entry_blocked_softc, playwright_overrecommend_static_rows]
trigger_slugs: [host_heaven-burns-re_news_3a4b5427, host_shadowverse-wb-_news_ef56405e, host_shinycolors-ido_news_1a96e971, host_another-eden-jp_news_57af7bcf]
date: 2026-05-27
---

# Generic Probe Verdict: 403 Soft 404 + Static Rows

## 요약

두 C-layer probe verdict 오분류를 일반화했다.

1. `probe.signals.classify`: 403 을 곧장 `BLOCKED_BOT` 으로 보던 경로에 앞서, anti-bot challenge marker 가 없는 S3 AccessDenied XML / explicit HTML 404 marker / empty-ish 403 body 를 `NOT_FOUND` 로 분류한다.
2. `probe.diagnose.diagnose`: S1 정적 진입이 OK 이고 `list_candidates.html_repeating_patterns` 에 row-like 후보가 충분하면, Playwright DOM 이 더 크다는 이유만으로 `JS 실행 필요` / S4 추천으로 덮지 않는다.

config 변경 없음. engine strategy / recognizer / prompt 변경 없음.

## OLD vs NEW

| slug | OLD | NEW | 근거 |
|---|---|---|---|
| `host_heaven-burns-re_news_3a4b5427` | `ENTRY_BLOCKED`, rc=5 capability_blocked | `TARGET_NOT_FOUND` | 모든 target 403 body 가 `application/xml`, `server: AmazonS3`, `<Code>AccessDenied</Code>` |
| `host_shadowverse-wb-_news_ef56405e` | `ENTRY_BLOCKED`, rc=5 capability_blocked | `TARGET_NOT_FOUND` | 모든 target 403 HTML 에 explicit `404` marker 반복, Cloudflare/Turnstile/Anubis marker 없음 |
| `host_shinycolors-ido_news_1a96e971` | `ENTRY_BLOCKED`, rc=5 capability_blocked | `TARGET_NOT_FOUND` | 모든 target 403 body 가 `application/xml`, `server: AmazonS3`, `<Code>AccessDenied</Code>` |
| `host_another-eden-jp_news_57af7bcf` | `JS 실행 필요`, recommended `Playwright headless + stealth (S4)` | `정적 HTTP로 충분`, recommended `httpx (S1.H2)` | S1.H2/H3/H4 OK + `#backnumber > li` cc=116 row 후보. Playwright DOM 이 크다는 신호보다 static row evidence 우선 |

## replay 결과

로컬에 없던 네 artifact 는 N100 에서 read-only artifact copy 로 받았다. N100 코드, git, service 는 변경하지 않았다.

Replay rebuilt diagnosis from saved artifact bodies, not from old stored classifications.

```text
heaven-burns-red: old_verdict='ENTRY_BLOCKED' -> new_verdict='TARGET_NOT_FOUND'; old_rec='통과한 전략 없음 — 추가 검토 필요' -> new_rec='통과한 전략 없음 — 추가 검토 필요'
  target_classes=[('S1.H2', 403, 'NOT_FOUND', ['soft not-found marker: S3 AccessDenied XML']), ...]
shadowverse-wb: old_verdict='ENTRY_BLOCKED' -> new_verdict='TARGET_NOT_FOUND'; old_rec='통과한 전략 없음 — 추가 검토 필요' -> new_rec='통과한 전략 없음 — 추가 검토 필요'
  target_classes=[('S1.H2', 403, 'NOT_FOUND', ['soft not-found marker: HTML 404 marker']), ...]
shinycolors: old_verdict='ENTRY_BLOCKED' -> new_verdict='TARGET_NOT_FOUND'; old_rec='통과한 전략 없음 — 추가 검토 필요' -> new_rec='통과한 전략 없음 — 추가 검토 필요'
  target_classes=[('S1.H2', 403, 'NOT_FOUND', ['soft not-found marker: S3 AccessDenied XML']), ...]
another-eden: old_verdict='JS 실행 필요 (Cloudflare 등)' -> new_verdict='정적 HTTP로 충분'; old_rec='Playwright headless + stealth (S4)' -> new_rec='httpx (S1.H2)'
  note0=정적 HTML row 후보가 충분함 — S1.H2 OK + selector #backnumber > li cc=116 sample=https://another-eden.jp/news/20190626/index.html 확인. Playwright DOM 이 더 크더라도 static rows 우선.
```

## heuristic 설계

### 403 soft 404

Anti-bot marker 검사 순서는 유지했다. `cf-chl-opt`, `cdn-cgi/challenge-platform`, `__cf_chl`, Anubis marker 등이 있으면 여전히 `BLOCKED_BOT` 이다.

그 뒤 403 에 한해 다음을 `NOT_FOUND` 로 본다.

- S3 XML: `content-type` 에 `xml`, `server: AmazonS3`, body 에 `<Code>AccessDenied</Code>`
- HTML 404 marker: HTML body visible text 에 `404` 반복 또는 `404` + `not found`
- empty-ish 403: visible text 80자 미만이고 raw body 200자 미만이며 Cloudflare/retry header 없음

### static rows vs Playwright

`static_vs_headless_check` 의 size rule 은 원래 "static shell 에 row 가 없고 Playwright 에만 row 가 생기는" 경우를 잡기 위한 강한 신호다. 다만 S1 이 OK 이고 probe 가 이미 row-like 후보 `child_count >= 10` + `sample_url` 을 확보했다면, verdict/recommendation 은 static/httpx 를 우선한다. Another Eden 처럼 정적 HTML 이 fragment loader 를 포함하고 Playwright 가 fragment 를 채운 경우, probe evidence 는 "S4 만 가능" 이 아니라 "static 경로로 풀 단서가 있음" 이다.

## Track B 6-layer audit

- E schema 거부: miss — config schema 가 아니라 probe verdict/recommendation 분류 문제.
- D retry feedback: miss — generated config 검증 실패 feedback 전에 probe diagnosis 가 잘못된 방향을 줌.
- C probe digest 신호: hit — HTTP body/header classification 과 diagnosis recommendation heuristic 을 수정.
- B few-shot: miss — 예제 config 추가로 해결할 사이트별 생성 문제가 아님.
- A system prompt: miss — prompt 입력 전 probe verdict 가 rc=5/S4 로 오도함.
- F engine code: miss — adapter/runtime 동작 변경 없이 probe layer 에서 판정 가능.

## 영향 범위

- `probe/signals.py`: 403 generic bot fallback 앞에 soft-not-found guard 추가.
- `probe/diagnose.py`: S1 OK + strong list row 후보가 있으면 Playwright size override 를 억제.
- `tests/probe_heuristics/test_signals_classify.py`: S3 AccessDenied, HTML 404 marker, empty 403, challenge-marker precedence fixture 추가.
- `tests/probe_heuristics/test_diagnose_static_rows_prefer_httpx.py`: static row 후보가 S4 recommendation 을 이기는 fixture 추가.

영향 사이트는 "403 == bot block" 으로 rc=5 에 빠진 S3/CloudFront static-site missing path 계열과, S1 OK + strong row candidates 가 있는데 S4 를 과추천받는 probe verdict 계열이다. Config files 는 건드리지 않았다.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS, 1650 PASS, 0 FAIL, 1 existing WARN.
- `python scripts/probe_smoke.py`: PASS, 1660 PASS, 0 FAIL, 1 existing WARN. Standard REPS artifacts were pulled/regenerated locally because this worktree initially lacked `output/probe`.
- artifact replay: 4/4 expected outcomes confirmed.
- `python scripts/vocab_lint.py`: FAIL on pre-existing avoid-term hits in `.claude/skills/hand-config/SKILL.md` and older `docs/cases/*`; changed files have no avoid-term hit.

`scripts/cases_index.py` / DB backfill / `docs/cases/INDEX.md` sync 는 이 codex chunk 의 HARD-STOP 범위 밖이라 실행하지 않았다.
