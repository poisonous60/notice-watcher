---
plan: Radiolab 류 SPA hydration 회복 — probe/digest 강화 3 option
session: 다음 step (D-layer recipe MVP 후속)
date: 2026-05-25
status: planned (codex 리뷰 전)
parent_case: docs/cases/host_radiolab-org_podcast_0080db5b.md
parent_plan: docs/cases/_plan_retry_recipes_2026-05-25.md
tags: [plan, probe, digest, spa, hydration, radiolab]
---

# Plan — Radiolab 류 SPA hydration 회복 (probe + digest 강화)

## 1. 문제 — recipe layer 가 못 봉합한 정보 부족

### 1a. 현황

`docs/cases/_plan_retry_recipes_2026-05-25.md` 의 D-layer recipe MVP 검증 결과:
- **TAL 회복 ✅** (시도 3 PASS 15건) — Recipe 1 fallback chain (guid number prefix + link 전체).
- **Radiolab 회복 X** — 5 시도 다 posts_nonempty 0건. recipe inject + text hint 전달은 됐으나
  LLM 이 진짜 row selector (`.radiolab-card .card-title-link .h2`) 추측 불가.

### 1b. root cause

Radiolab probe artifact 분석:

| 신호 | 결과 |
|---|---|
| probe headless capture (`list.html` = playwright `page.content()`) | hydration *전* 캡처 |
| `.radiolab-card` actual DOM element | 0개 |
| `.radiolab-card` CSS rule (inline `<style>`) | 박혀 있음 |
| `html_repeating_patterns` top 후보 | skeleton (`div.col-12.mb-6`) — false positive |
| LLM prompt 에 도착한 list_html | `<style>` 제거됨 (`engine/digest.py:clean_html`) |

**결론**:
- probe headless 가 *이미 playwright 로 캡처* 함 (구조적 가능). 단 `_wait_xhr_quiet(quiet_ms=300)`
  만 기다림 — Radiolab 의 Nuxt async data fetch (`https://api.wnyc.org/...recent_stories/...`)
  완료 전 capture 종료.
- digest 의 `clean_html` 가 `<style>` 다 제거 → `.radiolab-card` 등 component class 명세 LLM 안 도달.
- `html_repeating_patterns` heuristic 이 skeleton row 도 top 후보로 잡음 — LLM 함정.

= **probe + digest layer 의 정보 한계**. 모델 능력 문제 X, prompt 에 단서 자체 없음.

### 1c. 정보 흐름

```
real DOM (hydration 후)
  ↓ ❌ probe wait 부족 — Option 2 fix
playwright page.content() = list.html
  ↓ (raw HTML, <style> 포함)
build_digest → clean_html (remove <style>) → digest.list_html.html
  ↓ ❌ component class extract 없음 — Option 1 fix
LLM prompt
  ↓ html_repeating_patterns 의 skeleton top 함정
      ❌ Option 3 fix
LLM 추측
```

## 2. 해결 방식 — 3 option 다 구현 (직교 효과)

### Option 1: CSS component class extract (digest enhancement)

**자리**: `engine/digest.py`. `build_digest` 가 raw list.html (clean_html 전) 의 `<style>` 블록에서
component class 추출 → 새 키 `digest["list_candidates"]["css_component_classes"]`.

**알고리즘**:
1. raw_list_html 의 `<style>` 태그 collect (BeautifulSoup)
2. 각 `<style>` 안의 CSS rule 의 class selector regex 추출 (`\.([a-zA-Z][\w-]*)`)
3. frequency 카운트 (한 class 가 N rule 에 등장하면 +N)
4. reject filter:
   - utility class: `mb-*`, `mt-*`, `col-*`, `p-component`, `sm:*`, `lg:*`, `md:*`, `text-*`, `flex`,
     `grid`, `justify-*`, `items-*`, `font-*`, `bg-*` 류 (Tailwind/Bootstrap 노이즈)
   - chrome class: nav/header/footer/sidebar/menu/breadcrumb/skeleton/loading/placeholder/spinner/shimmer
     (`_SPA_WAIT_SELECTOR_BLOCKLIST_RE` 재사용 가능)
   - 너무 일반: `container`, `wrapper`, `inner`, `outer`, `body`, `main`, `header`, `footer`
5. frequency >= 2 + top 8 by frequency

**출력 schema**:
```json
{
  "css_component_classes": [
    {"class": "radiolab-card", "rule_count": 12, "co_classes": ["v-card", "card-title-link"]},
    {"class": "card-title-link", "rule_count": 8, "co_classes": ["h2"]},
    ...
  ]
}
```

**LLM 전달**:
- `prompts/config_writer.system.txt` 의 SPA 가이드에 한 줄 추가 — "SPA 사이트 의 정적 HTML 의
  `<style>` rule 에 자주 등장하는 component class (digest `list_candidates.css_component_classes`)
  가 hydration 후 row 후보".
- `engine/digest.py` 의 digest 출력에 그대로 dump (LLM prompt 의 meta JSON 안 포함).

**recipe 2 강화**:
- `generate/generator.py:_pick_spa_wait_selector` 가 fallback 으로 css_component_classes 도 참고.
  html_repeating_patterns 에 진짜 row 후보 없으면 (skeleton 만 잡힘) css class top 1-2 를
  wait_selector 후보로 박음.

### Option 2: probe hydration wait 강화

**자리**: `probe/fetch_headless.py` — `_wait_xhr_quiet` 또는 추가 wait.

**현재**: `quiet_ms=300, hard_timeout_ms=idle_timeout_ms` (보통 8000ms 의 사용자 설정).

**변경**:
- quiet_ms 를 800ms 로 증가 (Radiolab 류 async fetch 대응). 또는
- 추가 wait — `page.wait_for_function("document.querySelectorAll('a[href]').length > <baseline>", timeout=3000)`
  같은 *hydration 신호* 기다림. 단 baseline 어떻게 잡을지 모호.

**옵션 A (보수)**: quiet_ms 800 으로 globally. 모든 probe 800ms 더 느려짐 — 5초 → 5.8초 류.

**옵션 B (선택적)**: SPA detection — Nuxt/Next/React 식별자가 정적 HTML 에 있으면만 wait 강화.
- 신호: `<script>` 안 `__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`, `<div id="__nuxt">` 등.
- `probe/fetch_headless.py` 의 capture 함수가 SPA 신호 발견 시 quiet_ms 1500ms 까지 wait.
- 일반 사이트 영향 없음.

**옵션 B 채택**. SPA 신호 = `re.search(r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__|<div\s+id=\"__nuxt\"|<div\s+id=\"app\"", html, re.IGNORECASE)`.

**risk**:
- B-R1: SPA 신호 false-positive — 일반 사이트가 nuxt 글자 우연 매칭. → strict pattern (3개 이상 매칭 또는 unique tag)
- B-R2: 1500ms 도 부족한 사이트 — 그건 hand-config 또는 별도 fix.
- B-R3: probe 시간 늘어남 (SPA 만, ~1초). 받아들임.

### Option 3: skeleton row reject heuristic

**자리**: `probe/_html_repeating_patterns.py` 또는 backfill heuristic.

`html_repeating_patterns` 후보 점수 계산 시 row selector 의 class 에 skeleton/loading/placeholder/
p-skeleton/shimmer/spinner 박혔으면 *점수 0* 또는 list 에서 제외.

**알고리즘**:
- 후보 selector 의 모든 token (class/id/tag) 검사
- token 중 하나라도 `(skeleton|loading|placeholder|shimmer|spinner|ghost|empty-state)` 매칭 →
  reject (점수 -∞ 또는 list 에서 drop)

**효과**: Radiolab 의 false top (`div.col-12.mb-6` — skeleton row container) 제거. LLM 한테 top
후보로 더 이상 안 보여짐. 진짜 row 후보가 없으면 `html_repeating_patterns` 비어있게 — LLM 이
다른 신호 (css_component_classes, hydration JSON 등) 의존 유도.

**risk**:
- C-R1: class 이름에 우연히 `loading` 박힌 진짜 row — 매우 드물지만 가능. 매칭 token 만 reject (전체 element 살림).
- C-R2: 후보 1개도 안 남는 경우 → SPA recipe 가 발동 시 css_component_classes fallback 으로 보강.

## 3. 구현 자리 + 변경 파일

| 파일 | Option | 변경 |
|---|---|---|
| `engine/digest.py` | 1 | `_extract_css_component_classes` 함수 + `build_digest` 호출 + list_candidates 키 추가 |
| `prompts/config_writer.system.txt` | 1 | SPA 가이드 한 줄 추가 (component class 안내) |
| `generate/generator.py` | 1 | `_pick_spa_wait_selector` fallback 으로 css_component_classes 참고 |
| `probe/fetch_headless.py` | 2 | SPA 신호 detection + quiet_ms 강화 |
| `probe/_html_repeating_patterns.py` | 3 | skeleton/loading token reject filter (또는 backfill heuristic 자리) |
| `tests/probe_heuristics/test_css_component_classes.py` (신규) | 1 | CSS class extract 휴리스틱 unit |
| `tests/probe_heuristics/test_html_repeating_patterns.py` (확장) | 3 | skeleton reject 케이스 추가 |
| `tests/probe_heuristics/test_retry_recipes.py` (확장) | 1 | `_pick_spa_wait_selector` 의 css fallback |
| `docs/cases/_plan_radiolab_probe_digest_2026-05-25.md` | — | 이 plan |
| `docs/cases/host_radiolab-org_podcast_0080db5b.md` | — | 회복 결과 추가 |

## 4. 검증 절차

### 4a. fixture-only unit-test

- `test_css_component_classes.py`: radiolab list.html sample + 예상 출력 (`radiolab-card` 등 top
  N). utility/chrome class reject 확인.
- `test_html_repeating_patterns.py` 확장: skeleton class 박힌 row reject 케이스.
- `test_retry_recipes.py` 확장: html_repeating_patterns 비어있을 때 css_component_classes
  fallback 으로 wait_selector 후보 잡는지.

### 4b. 회귀

- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.
- 기존 251 configs (특히 45개 playwright_html) 회귀 0.

### 4c. 시뮬레이션

`scripts/_simulate_retry_recipes.py` 의 Radiolab 시나리오 — css_component_classes 박혀있을 때
recipe 2 의 patched candidate 의 wait_selector 가 `.radiolab-card` 등 잡는지.

### 4d. 진짜 회복 검증 — N100 register

**다시 probe 돌려야 함** (Option 2 적용 효과 측정):
```bash
ssh aaaa@n100-noticewatcher 'cd ~/notice-watcher && timeout 600 .venv/bin/python scripts/probe.py "https://radiolab.org/podcast" --lite'
```
그 다음 register:
```bash
ssh aaaa@n100-noticewatcher 'cd ~/notice-watcher && timeout 600 .venv/bin/python scripts/register.py "https://radiolab.org/podcast" --slug host_radiolab-org_podcast_0080db5b --reuse-probe --force --max-attempts 5'
```

기대: 시도 N 에서 posts_nonempty PASS + 등록 완료.

회복 X 면 — Option 2 의 quiet_ms 더 늘리거나 (1500→3000), 다른 hydration 신호 wait 추가.

## 5. risk 정리

| risk | severity | mitigation |
|---|---|---|
| Option 1 false-positive (utility class) | medium | utility regex blocklist + frequency threshold |
| Option 1 prompt token 증가 | minor | top 8 만 박음 + 짧은 JSON |
| Option 2 SPA detection false-positive | medium | strict pattern (3+ markers 또는 unique tag) |
| Option 2 probe 시간 증가 | minor | SPA detection 시만 +1초 |
| Option 3 진짜 row reject 위험 | minor | token 매칭만 (class 명에 skeleton 박힌 케이스 드뭄) |
| 245 기존 config 회귀 | critical | probe_smoke stage 3 PASS |

## 6. 다음 후속 (이번 plan 외)

- Radiolab 회복 후 — 비슷한 SPA (Nuxt/Next async data fetch) 8 slug 배치 재시도
- Option 1 의 css_component_classes 가 *진짜 row* 인지 검증하는 보조 heuristic
- probe hydration capture 시 networkidle 대신 *XHR response 패턴 매칭* (예: `api/.*recent`)

## 7. 참조

- `docs/cases/_plan_retry_recipes_2026-05-25.md` — 부모 plan (D-layer recipe MVP)
- `docs/cases/host_radiolab-org_podcast_0080db5b.md` — handcrafted config + D-layer 한계 기록
- `engine/digest.py:classify_site_kind` — site_kind 분류 (spa_rendered/high)
- `probe/fetch_headless.py:_capture_page_content` — playwright `page.content()` 호출 자리
- `probe/_html_repeating_patterns.py` — html repeating patterns heuristic
