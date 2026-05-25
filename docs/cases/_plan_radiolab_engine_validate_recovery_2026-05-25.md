---
plan: Radiolab 류 SPA 회복 — engine playwright_html validate flow 강화 (probe layer 외)
session: 다음 step (probe/digest 강화 후속)
date: 2026-05-25
status: planned (아직 구현 X)
parent_case: docs/cases/host_radiolab-org_podcast_0080db5b.md
parent_plans:
  - docs/cases/_plan_retry_recipes_2026-05-25.md (D-layer recipe MVP)
  - docs/cases/_plan_radiolab_probe_digest_2026-05-25.md (probe+digest 3 option)
tags: [plan, engine, playwright_html, spa, hydration, radiolab, validate, polling]
---

# Plan — Radiolab 회복: engine playwright_html validate flow 강화

## 1. 문제 — 박은 인프라 효과 측정 + 남은 영역

### 1a. 박은 것 (2026-05-25 6 commit)

| commit | 변경 | 효과 |
|---|---|---|
| `19e1815` | probe/digest 3 option (CSS extract / skeleton reject / SPA wait 1500ms) | ✅ CSS extract 작동 (radiolab-card 잡힘) |
| `809625a` | URL pagination heuristic (HTML anchor + HAR XHR) | △ Radiolab 미적용 (HAR 에 진짜 API fetch 안 박힘) |
| `9a25cf3` | pagination rtype fallback + SPA wait 3000ms | △ 효과 부분적 |
| `19ca03a` | SPA wait 3000→8000ms quiet, hard_timeout 12000 | ✅ probe artifact 에 진짜 cards 박힘 도움 |
| `6d054fd` | stylesheet block 해제 (Nuxt CSS 의존 hydration) | ✅ 정적 list.html 에 hydrated DOM 박힘 |
| `8d89229` | SPA marker quick check 50KB→200KB | ✅ Radiolab `__nuxt` 79KB 위치 잡음 |
| `8d279dc` | post_processor: strategy=playwright_html 면 idle/quiet/nav 강제 | ✅ cfg 의 timeout 정확 박힘 (idle 12000, quiet 800, nav 20000) |

### 1b. 효과 측정

**probe layer** ✅:
- probe artifact (`output/probe/<slug>/list.html`) 에 진짜 `.radiolab-card` 12개 DOM 박힘
- `html_repeating_patterns` 가 진짜 row sample_url 잡음 (`/podcast/6808128df...` 진짜 episode URL)
- `css_component_classes` top 1 = `radiolab-card` (rule_count 123)
- LLM 이 진짜 selector 박음 (`div.recent-episodes div.v-card.radiolab-card`)

**engine `playwright_html` validate flow** ❌:
- N100 `register --force --reuse-probe --max-attempts 5` = 5 시도 다 `posts_nonempty(0건)`
- LLM cfg + post_processor timeout 강제 적용된 상태에서도 0건
- = engine 의 `wait_for_selector` 가 12s 안 match 했는데도 `page.content()` 시점에 진짜 DOM 비어있음.
  **element exist (selector match) != fully hydrated DOM**.

### 1c. probe vs engine playwright_html 환경 차이 (진짜 root)

`probe/fetch_headless.py:_capture_page_content` flow:
1. `page.goto(wait_until="domcontentloaded")`
2. `_wait_xhr_quiet(quiet_ms=300)` 기본
3. SPA marker 검출 시 추가 `_wait_xhr_quiet(quiet_ms=8000, hard_timeout=12000)` (2026-05-25 박힘)
4. `page.content()` capture
5. resource block (font/image/media만, stylesheet 허용)
6. launch_args 특수 flag + fingerprint patch

`engine/strategies/playwright_html.py:_goto` flow:
1. `page.goto(wait_until="domcontentloaded")`
2. `_wait_xhr_quiet(quiet_ms=cfg.quiet_ms, hard_timeout_ms=cfg.idle_timeout_ms)` (cfg 값 사용)
3. `wait_selector` 있으면 `page.wait_for_selector(timeout=idle_timeout_ms)` — 매칭 시 *즉시 break*
4. `page.content()` capture
5. resource block 없음 (모든 resource fetch)
6. launch = `pw.chromium.launch(headless=True)` (bare) + playwright-stealth apply

**진짜 차이 = step 3 의 `wait_for_selector`**. probe 는 wait_for_selector 없이 quiet 시간 채움.
engine 은 selector match 즉시 break — Nuxt 의 hydration 이 *element 박힌 직후* 도 progressive
render 중일 수 있어 *content() 시점에 부분 DOM* 만 캡처.

가설:
1. `.radiolab-card` 가 DOM 에 *placeholder* 로 일찍 박힘 (skeleton replace 시점) → wait_for_selector
   match → page.content() → 그러나 그 시점에 child element (a.card-title-link 등) 아직 없음 →
   row_selector 매칭 시 child 0 → 0건
2. 또는 hydration 이 *batch* — 첫 1-2 cards 박히고 나머지 11-10 cards 가 추가 fetch 후

## 2. 해결 방식 — 3 option

### Option A: engine playwright_html 도 capture-detect-recapture (probe 패턴 포팅)

자리: `engine/strategies/playwright_html.py:_goto`.

```python
async def _goto(adapter, url, *, wait_selector=None):
    cfg = adapter.cfg
    page = adapter._page
    await page.goto(url, wait_until="domcontentloaded", timeout=nav_to)
    await _wait_xhr_quiet(page, quiet_ms=quiet_to, hard_timeout_ms=idle_to)
    if wait_selector:
        try:
            await page.wait_for_selector(wait_selector, timeout=idle_to)
        except Exception:
            pass
    # NEW: SPA marker 검출 시 추가 quiet (capture-detect-recapture)
    html = await page.content()
    if _has_spa_hydration_marker(html[:200_000]):
        await _wait_xhr_quiet(page, quiet_ms=2000, hard_timeout_ms=8000)
        html = await page.content()
    return html
```

비용:
- `playwright_html` 사용 사이트 (45 configs) polling 시점 SPA marker 검출되면 매번 +2-8초
- polling interval 5분 마다 이 비용 누적 — 큰 비용
- **mitigation**: cfg 에 `disable_spa_extra_wait: true` 키 박아서 사이트별 override

장점: 가장 단순. probe 와 동일 패턴.

### Option B: `wait_for_function` 로 row count 기반 wait

자리: `engine/strategies/playwright_html.py:_goto` 의 `wait_for_selector` 대체.

```python
if wait_selector:
    # row count 기반 wait — 단순 element exist 보다 정확한 hydration 신호
    try:
        await page.wait_for_function(
            f"document.querySelectorAll({wait_selector!r}).length >= 3",
            timeout=idle_to,
        )
    except Exception:
        pass
```

장점: hydration 완료 신호 정확 (≥3 cards 박혀야 break). 부분 render 시점 break 회피.

risk:
- B-R1: `wait_selector` 가 JS string 으로 사용 — escape 문제 (특수 문자, quote). 사이트 별로 안 통할 수도.
- B-R2: 사이트가 진짜 row 3개 미만이면 timeout 끝까지 기다림. cfg 별 `wait_count` 옵션 필요.

### Option C: cfg 새 키 `list.wait_count` 박고 LLM 한테 안내

`list.wait_count` 추가 (옵션, 기본 1):
- LLM cfg 에 `wait_count: 3` 박으면 wait_for_function 으로 ≥3 row 기다림
- 기본 1 이면 기존 wait_for_selector 동작 유지 (backward compat)

비용: cfg schema + engine + prompt + LLM 추측 의존.

## 3. 구현 자리 + 변경 파일

| 파일 | Option | 변경 |
|---|---|---|
| `engine/strategies/playwright_html.py` | A or B | `_goto` 안 capture-detect-recapture 또는 wait_for_function |
| `engine/config_schema.py` | C | `list.wait_count` 키 추가 |
| `prompts/config_writer.system.txt` | C | wait_count 안내 |
| `engine/digest.py` | A | `_has_spa_hydration_marker` 함수를 engine 으로 옮기거나 별도 module (probe → engine 의존 회피) |
| `tests/probe_heuristics/test_playwright_strategy.py` (신규) | A/B/C | fixture-only — SPA marker / wait_for_function 시그니처 검증 |

## 4. 검증

### 4a. fixture-only

- SPA marker detection 함수 unit-test
- cfg schema validation

### 4b. 회귀

- `probe_smoke --stage 3 --stage 5` PASS
- 기존 45 playwright_html configs 회귀 0

### 4c. 진짜 회복 검증

```bash
ssh aaaa@n100-noticewatcher 'cd ~/notice-watcher && timeout 600 .venv/bin/python scripts/register.py "https://radiolab.org/podcast" --slug host_radiolab-org_podcast_0080db5b --reuse-probe --force --max-attempts 5'
```

기대: 시도 N 에서 posts_nonempty PASS + 등록 완료.

회복 X 면 — Option A→B→C 순서로 시도 또는 *handcrafted config 정답* 확정.

## 5. risk

| risk | severity | mitigation |
|---|---|---|
| Option A polling 시점 매번 +2-8초 비용 | medium | SPA marker 검출 시만 + cfg `disable_spa_extra_wait` override |
| Option B wait_selector escape | medium | JS literal 안전 변환 함수 |
| Option B 진짜 row <3 사이트 timeout | minor | cfg `wait_count` 옵션 (Option C 와 결합) |
| 45 playwright_html configs 회귀 | critical | probe_smoke + 샘플 사이트 1-2개 register 재실행 |
| handcrafted config (수동 등록 사이트) 영향 | minor | setdefault 패턴 사용 (LLM 명시 값 보존) |

## 6. 추천 순서

1. **Option A 먼저** (가장 단순, probe 와 동일 패턴) — Radiolab register 검증
2. 회복 시 → 끝
3. 회복 X 면 Option B → C 차례
4. 다 안 되면 handcrafted config 정답 확정 (이번 case 의 §해결 그대로)

## 7. 다음 세션 진입 가이드

### 7a. 컨텍스트

1. 이 plan 문서
2. `docs/cases/host_radiolab-org_podcast_0080db5b.md` 의 §해결 + 2026-05-25 추가 섹션
3. `docs/cases/_plan_radiolab_probe_digest_2026-05-25.md` (probe 강화 완료)
4. `engine/strategies/playwright_html.py:_goto` 현재 코드 (lines 125-138)
5. `probe/fetch_headless.py:_capture_page_content` + `_has_spa_hydration_marker` 패턴 참고

### 7b. 첫 명령

```bash
# 1. engine playwright_html 의 현재 _goto 봄
grep -n "def _goto\|wait_for_selector\|page.content" engine/strategies/playwright_html.py

# 2. Option A 적용 — _goto 안 capture-detect-recapture loop
# 3. probe_smoke PASS 확인
# 4. N100 register --force --reuse-probe Radiolab 1건
# 5. 회복 시 case 문서 업데이트
```

### 7c. 작업 ALLOW-LIST

- `engine/strategies/playwright_html.py`
- `engine/digest.py` (SPA marker 함수 옮길 경우)
- `tests/probe_heuristics/test_playwright_strategy.py` (신규)
- `docs/cases/host_radiolab-org_podcast_0080db5b.md` (회복 결과)

### 7d. 작업 금지

- `probe/fetch_headless.py` (이번 plan 영역 아님 — 이미 박힌 6 commit 그대로 유지)
- `configs/host_radiolab-org_podcast_0080db5b.json` (handcrafted 보존)
- `prompts/config_writer.system.txt` (Option C 한정 — A/B 만 진행할 땐 안 변경)
- N100 ssh 의 코드 편집 — dev box only

## 8. 후속 (이번 plan 외)

- 다른 Nuxt/Next SPA 사이트 batch 재시도 — Option A/B/C 의 generic 효과 측정
- engine playwright_html 의 stealth/launch_args 도 probe 와 통일 (env 차이 더 줄임)
- DOM mutation observer 패턴 — element exist + child count + text content 셋 다 기다림

## 9. 참조

### commit chain (이미 박힘)

- `19e1815` probe/digest 3 option MVP
- `809625a` URL pagination heuristic
- `9a25cf3` pagination rtype fallback + SPA wait 3000ms
- `19ca03a` SPA wait 8000ms (probe)
- `6d054fd` stylesheet block 해제
- `8d89229` SPA marker quick check 200KB
- `8d279dc` post_processor timeout 강제 (cfg 단)
- `8301e24` case 문서 진단

### 코드 위치

- `engine/strategies/playwright_html.py:125-138` — `_goto` (수정 자리)
- `engine/strategies/playwright_html.py:76-105` — `open_session` (launch/context 설정)
- `probe/fetch_headless.py:_has_spa_hydration_marker` — SPA detect (포팅 자리)
- `probe/fetch_headless.py:_capture_page_content` — capture-detect-recapture 패턴 원본
- `scripts/register.py:_enforce_site_kind_config` — post_processor (이미 박힘)

### test 위치

- `tests/probe_heuristics/test_css_component_classes.py` — Option 1 CSS extract
- `tests/probe_heuristics/test_html_repeating_patterns.py` — skeleton reject
- `tests/probe_heuristics/test_pagination_hints.py` — URL pagination
- `tests/probe_heuristics/test_playwright_strategy.py` — *신규 작성 자리*

### 진짜 회복 검증 URL

- Radiolab: `https://radiolab.org/podcast` (Nuxt SPA, handcrafted config 정답)
- (선택) 다른 Nuxt/Next SPA 사이트 — batch hand-config 큐 확인
