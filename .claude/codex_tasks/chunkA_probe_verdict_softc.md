# Chunk A — probe verdict C-layer (cross-site, 4 sites)

## 목표 (Track B C-layer, generic improvement)

`probe/signals.py` + `probe/diagnose.py` 의 verdict 휴리스틱 2종 모순 봉합. *수동 config 박지 X*. 같은 batch 의 4 sites 가 같은 fail layer 신호.

### A1. 403 soft-404 오분류 (3 sites cohort)

현재: `probe/signals.py:158` `bad_status = status in (403, 429, 503)` → 403 = 무조건 `BLOCKED_BOT`. `probe/diagnose.py:267` 모든 target 이 `BLOCKED_BOT` 이면 verdict=`ENTRY_BLOCKED` → register rc=5 (`capability_blocked`).

실제: 4xx body 가 *S3-style AccessDenied XML* 또는 *HTML page with explicit 404 markers* 또는 *empty/empty-ish* 면 *진짜 anti-bot 아님* — soft 404 (URL_DEAD). anti-bot 은 본문에 challenge marker (Cloudflare ray id / Turnstile / Anubis PoW / JS-challenge) 있어야 함.

### A2. static rows 있는데 playwright 추천 모순 (1 site)

`probe/diagnose.py:124` "JS 가 카드/목록 그리는 사이트 — strategy=playwright_html 필수" + `:149` `recommended_strategy = "Playwright headless + stealth (S4)"` 가 static list_candidates 에 row-like 요소 충분 (cc≥10) 있을 때도 트리거. 사용자 명시: `모순: static 이미 row 있는데 playwright recommend ← 이런거 고쳐서`.

## 동료 brief (cohort, 4 sites — 같은 batch 안)

| slug | URL | fail signal | probe artifact |
|---|---|---|---|
| host_heaven-burns-re_news_3a4b5427 | https://heaven-burns-red.com/news/ | rc=5 ENTRY_BLOCKED; S3 application/xml `<Code>AccessDenied</Code>` body | output/probe/host_heaven-burns-re_news_3a4b5427/ |
| host_shadowverse-wb-_news_ef56405e | https://shadowverse-wb.com/news/ | rc=5 ENTRY_BLOCKED; HTML body `<title>Shadowverse...</title>` + `404 404 404` markers | output/probe/host_shadowverse-wb-_news_ef56405e/ |
| host_shinycolors-ido_news_1a96e971 | https://shinycolors.idolmaster-official.jp/news/ | rc=5 ENTRY_BLOCKED; S3 application/xml `<Code>AccessDenied</Code>` body | output/probe/host_shinycolors-ido_news_1a96e971/ |
| host_another-eden-jp_news_57af7bcf | https://another-eden.jp/news/ | rc=1 gen_fail; static `#backnumber > li` cc=116 row 있는데 verdict=`JS 실행 필요`, recommended=playwright. agentic ERR_NAME_NOT_RESOLVED on Page.goto | output/probe/host_another-eden-jp_news_57af7bcf/ |

ship evidence: 사용자 직접 인용 — `https://another-eden.jp/news/ ... 이건 되야할 거 같고`. catalog batch operator 흐름이지만 사용자가 명시 sips 요청.

## 수정 자리 (worktree 자유 편집)

기본 surface (codex 가 fit 판단해 다른 자리도 OK — 단 evidence-based):
- `probe/signals.py:146-187` — 403 분류. S3/empty/404-marker body 의 NOT_FOUND classification 추가.
- `probe/diagnose.py:100-160` 의 verdict + recommended_strategy 빌드. static row count ≥ threshold (예: 10) AND target list-page S1.* OK 면 verdict 에 `JS 실행 필요` 추가 X / recommended=`httpx (S1.*)` 우선.
- `probe/diagnose.py:267` ENTRY_BLOCKED 조건 — body marker 없으면 TARGET_NOT_FOUND 로 fallback.

A1 / A2 *둘 다* 봉합. 한쪽만 박지 X.

### S3 AccessDenied XML pattern (구체)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Error><Code>AccessDenied</Code><Message>Access Denied</Message>...
```
Response header `content-type: application/xml` + `server: AmazonS3` + body contains `<Code>AccessDenied</Code>` = S3 soft 404.

### HTML 404-marker pattern (구체)
shadowverse-wb body — status=403 but `<title>Shadowverse...</title>` + body contains repeated `404` text. challenge marker 0 (Cloudflare/Turnstile 등).

### static rows pattern (구체)
another-eden — `output/probe/host_another-eden-jp_news_57af7bcf/list_candidates.json` 의 `html_repeating_patterns` 에 cc=116 entry. S1.* (httpx static) 응답 200 OK + content cc≥10 면 verdict 에 `JS 실행 필요` 추가 X.

## 검증 (의무)

1. `python scripts/probe_smoke.py` exit 0 + new fixture (S3 AccessDenied 1 case + HTML 404-marker 1 case + static-rows-vs-playwright contradiction 1 case).
2. **실제 artifact replay** (4 sites):
   ```bash
   python -c "
   import json
   from probe.diagnose import build_diagnosis
   # 4 sites 각각: probe/_contract artifact → build_diagnosis → verdict + recommended_strategy print
   # NEW vs OLD 비교 인쇄.
   "
   ```
   기대:
   - heaven-burns-red/shadowverse-wb/shinycolors → verdict=`TARGET_NOT_FOUND` (현재 ENTRY_BLOCKED)
   - another-eden → recommended=`httpx (S1.*)` (현재 Playwright S4) + verdict 에 `JS 실행 필요` 없음
3. 영향 함수 list: `signals.classify` · `diagnose.build_diagnosis`.

## case file (의무)

`docs/cases/_generic_probe_verdict_soft404_and_static_rows.md` 신규 작성. frontmatter:
```yaml
slug: _generic_probe_verdict_soft404_and_static_rows
url: (generic)
status: "🛠️ improved — probe verdict 2종 모순 봉합"
outcome: improved
fix_layer: C
failure_keys: [entry_blocked_softc, playwright_overrecommend_static_rows]
trigger_slugs: [host_heaven-burns-re_news_3a4b5427, host_shadowverse-wb-_news_ef56405e, host_shinycolors-ido_news_1a96e971, host_another-eden-jp_news_57af7bcf]
date: 2026-05-27
```

body: 4 sites OLD vs NEW 비교 표 + replay 결과 + heuristic 룰 설명.

## §0c HARD-STOP

- commit 금지 (Claude 가 함).
- push 금지.
- N100 배포 금지.
- worktree 안 모든 자유 편집 OK (probe/, scripts/, tests/, docs/). 외부 파일 X.
- result.md 마지막 줄에 변경 파일 list + 영향 함수 list + replay 표 인쇄.

## §0c-회피 게이트 (자기-audit)

1. 4 sites 중 *2+ 가 같은 fail layer signal* — 일반화 후보 punt 금지. 4 sites 모두 봉합되는 단일 수정.
2. probe artifact 직접 읽고 (`output/probe/host_*/`) 비교. cohort 통계 봐야.
3. `no_change` defer X — 두 모순 다 fix.
4. case body 일반화 후보 섹션 비우면 audit FAIL.
