---
slug: host_fate-go-jp_news_92f8d1f5
url: https://www.fate-go.jp/news/
status: "🧩 수동 config — canonical 도메인 (news.fate-go.jp/) httpx_html"
outcome: handcrafted
fix_layer: none
failure_keys: [err_name_not_resolved, canonical_url_change_subtle, www_to_news_subdomain_redirect, article_body_len]
date: 2026-05-27
config_strategy: httpx_html
tags: [hand-config, game-mobile, ja, jp, canonical-subdomain]
---

## 진단

- live: `curl -sIL https://www.fate-go.jp/news/` → 301 → `news.fate-go.jp/news/` (자체도 meta refresh → `/`); `curl -sIL https://www.fate-go.jp/2026/05/2026_grand_caster_cp/` → 301 → home (`/`). canonical list = `https://news.fate-go.jp/` 정적 200 OK 19108 bytes, `ul.list_news > li` 10 row.
- last_feedback: 1차 drain `ERR_NAME_NOT_RESOLVED at www.fate-go.jp` (chunk A F-layer fallback 부분 동작 — list 통과 후 article_body_len 0 자)
- diagnosis verdict: `JS 실행 필요 stealth (S4)` — Playwright stealth race + canonical URL 모호.
- 사용자 입력 URL (`www.fate-go.jp/news/`) 의 article URL 들이 home 으로 301. chunk B canonical_url_change fix 가 article=200 OK 라 못 잡음 (Playwright reprobe 가 redirect 따라 home 받아 200 OK report).

## E/D/C/B/A/F audit

- E: miss
- D: miss
- **C: hit candidate** — chunk B canonical_url_change detect 가 *article HTTP 응답 status* 만 봄. *redirect chain*(article URL → home redirect) 까지 봐야 false-negative 차단. 후속 chunk 후보.
- B: miss
- A: miss
- F: miss

C-layer hit (deferred) — 본 case 는 hand-config 으로 봉합. C-layer lift 는 후속.

## Track A 결정

- 4a Track B: C deferred (lift 후속), E/D/B/A/F miss
- 4b Track A 진입: ship 명시 = 사용자 첫 메시지 "수동 config 만들라고 triage 큐 hand-config 돌린건데 잔여가 남을 수가 있나?" + "진행해" → batch 의 명시 ship 승인 (all-residual scope) → Track A OK
- 4c context: operator flow + 명시 ship → Track A 진입
- 4d park bucket: N/A

## 수동 config 절차

1. live 확인 — `www.fate-go.jp/2026/05/<slug>/` 모두 → home redirect (article dead). canonical = `news.fate-go.jp/`.
2. canonical list page (`news.fate-go.jp/`) 정적 HTML 19108 bytes, `ul.list_news > li` 10 row.
3. canonical article (`news.fate-go.jp/2026/05/2026_new_chapter_cp3/`) 200 OK, body 2250 chars (selector=`main`).
4. config: slug 보존 (`host_fate-go-jp_news_92f8d1f5` — 사용자 input URL hash). `list.url_template` = canonical 도메인. `site=www.fate-go.jp` (input 보존) + `_source_url` (input 보존). `_note` 에 canonical 변경 명시.
5. strategy=httpx_html (canonical 정적 OK — stealth/playwright 불필요, DNS race 완전 회피).

## 검증

- schema PASS
- smoke fetch_list = 9 rows + body 10407 chars
- local register: baseline 9건 등록 ✓
- probe_smoke (post-merge): exit 0 PASS 1672

## 일반화 후보 (deferred)

`canonical_url_change` chunk B fix 확장 — *article URL 의 redirect chain* (Playwright 가 따라가는 redirect) 도 검출해 `canonical_url_change` reject 박기. 현재 fix 는 status 만 봄 (404 검출). subtle redirect (301 → home) 는 status 200 으로 false-negative.

후속 chunk 자리: `scripts/register.py` preflight reprobe 후 `final_url != original_article_url` 검증 (Playwright `Response.url` 또는 HAR final navigation entry).
