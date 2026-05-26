# 2026-05-26 anti-bot + cookie consent 통합 (research session 3 박힘)

merge commit `30912fd` (main). branch `session-integration-s3` 10 commit 묶음. dev box 작업, N100 deploy 완료.

## 1. 동기

batch `2026-05-24-games-kr` 의 rc=5 (capability_blocked) 9건이 트리거:
- 6 사이트 = 진짜 anti-bot (Cloudflare 1 + 자체 WAF 4 + SPA route 1)
- 3 사이트 = 분류기 false-positive (URL guess 오류, transient 200)

세션 1 = cookie banner 심층 조사 (`output/research_session1_cookie_banner.md`).
세션 2 = Cloudflare 우회 심층 조사 (`output/research_cloudflare_findings.md`).
세션 3 = 통합 디자인 + 실측 (`output/research_session3_integration.md`).

## 2. 박힌 commit (시간 순)

| commit | scope |
|---|---|
| ea490ad | `WAF_406_BLOCK` verdict 태깅 + register curl_cffi 권장 메시지 |
| a9c0427 | consent dismiss — KNOWN_CMP IDs (24) + queryDeep open-shadow piercing + iframe handler |
| 96cb40a | FAILED.last_feedback msgs propagate + WAF_406 7-case fixture |
| fc84c9d | Patchright drop-in (probe + engine, lazy fallback to playwright) |
| 0f1b3e7 | consent — frame reject-first + main DOM hide step + MPL-2.0 notice |
| 0182719 | curl_cffi_html strategy 신규 (Chrome TLS/JA3 임퍼소네이트) |
| 7cbb0b0 | CF interstitial wait 8s → 30s 조건부 |
| 0e37125 | _detect_cmp + consent.json artifact (IAB TCF/CCPA/GPP) |
| f00c3b4 | curl_cffi_html JSON schema/validate + runtime CF wait + goto-timeout CF recovery |
| 74e972f | consent.<target>.json — target-aware artifact name |

## 3. 자동화 매트릭스 (어디까지 자동인가)

### 3a. probe (1회 등록 시 진단)

| 기능 | 자동 |
|---|---|
| `_detect_cmp` + `consent.<target>.json` artifact | ✅ fetch_with_capture 가 매번 호출 |
| consent dismiss (KNOWN_CMP + shadow + iframe + reject→hide→accept 3단계) | ✅ Phase 9b click probe 가 자동 사용 |
| Patchright drop-in (S4) | ✅ try import → 자동 swap (binary 설치 시) |
| CF interstitial wait 30s 조건부 | ✅ `_is_cloudflare_interstitial` 가드 통과 시만 |
| goto-timeout CF recovery | ✅ 자동 |
| WAF_406 verdict 태깅 | ✅ diagnose.py 가 모든 정적 진입 status==406 시 자동 |

### 3b. register (등록 결정)

| 기능 | 자동 |
|---|---|
| WAF_406 메시지 분기 (curl_cffi 권장 안내) | **메시지만** 자동. *strategy swap 시도 X* |
| FAILED.last_feedback 의 _policy_check msgs propagate (stale 메시지 봉합) | ✅ |
| **ladder 자동 시도 (httpx → curl_cffi → patchright → storage_state)** | ❌ **미구현 — follow-up** |

### 3c. engine (런타임 polling — 등록 후 매 시간)

| 기능 | 자동 |
|---|---|
| Patchright runtime (playwright_html.open_session) | ✅ try import → adapter._engine_label 기록 |
| CF wait runtime (playwright_html._goto) | ✅ probe 와 같은 regex sync 미러링 |
| curl_cffi_html strategy 사용 | ❌ **config 에 `strategy: curl_cffi_html` 박혀야** — register 가 자동 박지 X |

## 4. 실측 결과 (dev box KR consumer IP 183.99.x — 2026-05-26)

| URL | 도구 | 결과 |
|---|---|---|
| `example.com` | Patchright headless | ✅ 3.5s |
| `pubg.com/en/news/` (회귀 f135f35) | fetch_with_capture (engine=patchright) | ✅ OK 200, body 80KB, cookie 잔존 = 자연 텍스트 (banner dismiss 성공) |
| `plaync.com/ko-kr/board/notice/list` (회귀 f15f1e4) | 같음 | ✅ OK 200, 85KB |
| `valofe.com` / `icarus.valofe.com` × 4 | curl_cffi (chrome/chrome131/safari17_2_ios/edge99 4 target) + ko-KR Accept-Language + Sec-CH-UA | 모두 ❌ 406 |
| 같음 | Patchright + 5s wait + reload | 1st=406 + JS challenge body + `FECWS`/`FECAS` cookies set, reload=403 |
| `crossfire.z8games.com` (Cloudflare) | httpx | ❌ 403 |
| 같음 | curl_cffi chrome | ✅ **HTTP 200 — full HTML** |
| 같음 | Patchright (15s/30s/networkidle/domcontentloaded/commit 모두) | ❌ TIMEOUT (connection-level block — 1 byte 도 안 받음) |

## 5. vendor 식별

### 5a. 능력 한계 확정: WAPPLES FEC (Forward Engine Challenge)
- vendor: **Penta Security WAPPLES** (KR enterprise WAF)
- 시그너처: body 안 `<script src="/_fec_sbu/fec_wrapper.js">` + `<script src="/_fec_sbu/hxk_fec_*.js">` + `FECWS`/`FECAS` cookies
- 우회: open-source 도구 *없음*. paid solver 도 KR WAF 미지원. residential proxy 도 효과 0 (이미 KR IP).
- 영향 사이트: valofe.com × 2, icarus.valofe.com × 2 (확인). 추가 KR 게임사·금융 일부 가능성.
- 처리: capability_blocked 영구 분류. follow-up 으로 verdict 태깅 (`WAPPLES_FEC_BLOCK`) + register 메시지 추가.

### 5b. ladder 순서 reality
세션 2 §1.2 권고 "Patchright 가 stealth 부족 대체" 는 *일부* 케이스 (cookie modal·SPA hydration) OK. 그러나 Cloudflare 적극 모드 사이트 (z8games) 는 **curl_cffi > Patchright** — Cloudflare 가 Chromium 자동화 fingerprint 적극 탐지, raw TLS impersonate (libcurl/BoringSSL) 만 통과시킴.

→ 세션 3 의 ladder `httpx → curl_cffi → Patchright → storage_state` 가 reality 와 부합. 자료 기반 가설을 실측이 확인.

## 6. codex 리뷰 결과 (13 findings)

3차 codex review 위임. 모두 `output/codex_review_*_task.result.md`.

| 라운드 | 대상 | findings | 처리 |
|---|---|---|---|
| 1 | P-5 (WAF_406) | 3 (1 medium S1.curl 메시지 약속·1 medium FAILED stale·1 low test) | commit 96cb40a |
| 2 | P-1~3 (consent) | 3 (1 high frame reject-first 없음·1 medium hide 누락·1 medium MPL notice 부족) | commit 0f1b3e7 + THIRD_PARTY_NOTICES.md |
| 3 | P-6/7/8/4 묶음 | 7 (2 high schema/validate·2 medium runtime CF wait + goto-timeout·3 low _engine_label · consent overwrite · cmp notable truncation) | commit f00c3b4 + 74e972f. LOW 5 + LOW 7 deferred |

## 7. follow-up (미구현)

### 7a. register ladder 자동 시도
현재: BASELINE_BLOCKED → 메시지 안내. 사용자가 hand-config 로 curl_cffi config 박아야 함.
원하는 동작: probe 가 verdict 따라 자동 retry — `httpx 실패 → curl_cffi 재시도 → patchright 재시도 → cap_blocked`. 별도 PR.

### 7b. WAPPLES FEC 자동 검출
body 에 `/_fec_sbu/` 또는 `FECWS`/`FECAS` cookie 검출 시 verdict 에 `WAPPLES_FEC_BLOCK` 태깅. register 가 `안내: open-source 우회 불가, capability_blocked 영구` 메시지. WAF_406 패턴과 동일.

### 7c. polling trace 의 `_engine_label` 노출 (codex P-6789 LOW 5)
`adapter._engine_label` 저장만 하고 trace span/post raw 에 안 나감. poll_runs/poll_site_runs 스키마 변경 필요 — Patchright A/B 측정 가능해짐.

### 7d. cmp digest field promotion (codex P-6789 LOW 7)
현재 `cmp:` 가 `notable` list 에만 박힘. digest/report 가 notable 을 첫 2-3 entry 만 보여 truncation 위험. structured field 로 승격.

### 7e. storage_state Discord UX 옵션 A
세션 2 §4.3 디자인. cf_clearance cookie 수동 복붙 → polling 에서 재사용. cf 강한 challenge 사이트 (Turnstile interactive) 의 유일 통과 경로. 봇 명령 `/cookies` + `output/storage_state/<slug>.json` write + .gitignore 강제 + pre-commit hook. ROI 미정 — 사용자 수 < 10 이면 defer.

### 7f. Camoufox 도입 검토 트리거
Patchright + curl_cffi 둘 다 실패하는 사이트 batch ≥3건 누적 시. 현재 정황 (WAPPLES FEC = paid solver 도 X) 으론 Camoufox 도 효과 의문.

## 8. 정책 결정 잠금 (이 batch 에서 박힘)

- **CAPTCHA solver auto (2captcha/CapSolver)**: NO. 비용 ROI X (월 $2) + 정책 (Turnstile interactive = "사람만" 의지).
- **Residential proxy (BrightData/Oxylabs/IPRoyal)**: NO. N100 = KR consumer ISP 이미 residential, botnet sourcing risk (Krebs 2025-10), Reddit v. Oxylabs 법적 risk.
- **Botnet-backed proxy (IPIDEA/360Proxy/922Proxy/ABCProxy)**: NO. Badbox 2.0.
- **fingerprint mimicry (Patchright, curl_cffi)**: YES. 사이트의 "fingerprint=Python" 만 보고 차단은 우리 측 위생 부족 정정. Chrome impersonation = 정상 통과 attempt.
- **consent 정책**: reject → hide → accept 3단계. 자동 Accept 우선 X (PIPA 2024 / CNIL 2025-06). 자동 PIPA 동의 wall · 연령확인 = policy_reject skip.

## 9. 관련 파일

- 코드: `probe/fetch_headless.py`, `probe/diagnose.py`, `engine/strategies/playwright_html.py`, `engine/strategies/curl_cffi_html.py` (신규), `engine/config_schema.py`, `scripts/register.py`, `requirements.txt`, `THIRD_PARTY_NOTICES.md` (신규)
- fixture: `tests/probe_heuristics/test_diagnose_waf_406.py` (7 cases)
- 연구 doc: `output/research_session1_cookie_banner.md`, `output/research_cloudflare_findings.md`, `output/research_session3_integration.md` (§7 = drop-in 실측 결과)
- codex review: `output/codex_review_p5_task.result.md`, `output/codex_review_p13_task.result.md`, `output/codex_review_p6789_task.result.md`
