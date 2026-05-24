---
plan: D-layer retry feedback dynamic injection (MVP 2 recipe)
session: 다음 세션 진입용 (이번 세션 미진행)
date: 2026-05-25
status: planned (codex plan 리뷰 통과 — Y, 단 그대로 X)
parent_retro: docs/cases/_session_retro_2026-05-24_podcast.md (§7f 후속 후보 2번)
plan_review: output/codex_generic_podcast-h-plan-review-task_prompt.result.md
tags: [plan, retry, dynamic-injection, llm-weight, podcast]
---

# Plan — D-layer retry feedback dynamic injection (MVP 2 recipe)

## 1. 문제

### 1a. 무엇이 일어났나 (출처)

옵션 A (site_kind enum) commit `4175415` HEAD 박힌 후 8 slug podcast batch 자동생성 테스트 결과 (`_session_retro_2026-05-24_podcast.md` §7d):

| slug | site_kind 결과 | register 결과 |
|---|---|---|
| cbs | (404) | ✅ 자동 거부 |
| **dotnetrocks** | rss med (가짜 link_rel /feed) | ❌ gen_fail |
| **thisamericanlife** | rss med (HAR XML primary) | ❌ gen_fail post_id_unique 3회 반복 |
| oxide | hybrid med (transistor primary) | ✅ 자동생성 30건 |
| **radiolab** | spa_rendered high | ❌ gen_fail posts_nonempty / title_nonempty 3회 반복 |

= 1/5 자동생성 + 1 자동 거부. **3건 fail = LLM weight 부족** (link_rel 검증 한계는 별도 후속).

### 1b. fail 진단 (root cause)

**thisamericanlife** (`feeds.thisamericanlife.org/talpodcast`):
- 진짜 RSS XML (item 5+, application/rss+xml).
- guid 형식 = `"46156 at https://www.thisamericanlife.org"` (공백 + URL 결합) → 안정 ID X.
- 정확한 fix = `post_id` source 를 `link` path tail 추출 (`regex_extract "/([^/?#]+)/?$"`).
- prompts/config_writer.system.txt 의 RSS post_id 룰 박혀있음 (commit `3e7fbcc`):
  > RSS item 의 `<guid>` 가 긴 원문/URL/문장 조합이라 `post_id_stable_shape` 를 깰 것 같으면 guid 를 post_id 로 쓰지 말고, `link` 의 path tail 을 우선 써라.
- 그러나 **LLM 이 retry 3회 동안 일관 무시** — concat title|url / link 통째 / 잘못된 transform 박음.

**radiolab** (`radiolab.org/podcast`):
- Nuxt SPA — server-rendered HTML 에 loading skeleton (`div.col-12.mb-6` 등) 만 들어옴, 진짜 row 는 hydration 후 `div.radiolab-card.v-card`.
- handcrafted config 의 진짜 selector = `.radiolab-card .card-title-link .h2` (commit `6ea2231`).
- 자동생성 retry 3회 = strategy/selector 변경 시도 다 fail (`posts_nonempty 0건` 또는 `title_nonempty`).
- prompts 의 spa_rendered hint 박혀있음 (commit `04817bf`).
- 그러나 **LLM 이 skeleton row 를 진짜 row 로 오인 + wait_selector 정확 selector 못 잡음**.

**dotnetrocks** (`dotnetrocks.com/RSS`):
- Blazor SPA — `/RSS` path 자체가 HTML 페이지. `/feed` (link rel) 도 HTML.
- 진짜 RSS endpoint 없음.
- site_kind=rss med + primary_feed_url=`/feed` (link_rel) — LLM 이 그대로 박음 → 0건 fetch.
- 이건 *link_rel validate 누락* 영역 (별도 후속, **이번 plan 외**).

### 1c. retry feedback 구조 (현재)

`generate/generator.py:_enrich_retry_feedback` ([generator.py:29~128](generate/generator.py#L29-L128)) 4 영역:
1. 직전 시도 cfg echo (list/article JSON)
2. probe 정적 HTML top 7 repeating patterns 재표시
3. probe 다른 list 전략 후보 카운트
4. attempt_history (strategy/selector/fails) + 같은 hard fail 2회+ 시 경고

**다 자연어 hint** — LLM free decision. 같은 fail 3회 반복도 LLM 이 prompt 룰 무시.

`generate/generator.py:generate_config_validated` ([generator.py:195+](generate/generator.py#L195)) retry loop = max_attempts=3 default. attempt N>=2 = retry round (call_site="config_retry" routing).

`generate/prompt.py:build_retry_prompt` ([prompt.py:99](generate/prompt.py#L99)) = `prev_config` 를 *"이전 실패 config (똑같이 박지 마라)"* 로 표시.

## 2. 해결 방식

### 2a. 핵심 — D-layer retry feedback dynamic injection (MVP 2 recipe)

같은 fail key 2회+ 반복 시 *결정론 봉합 룰* 강제 inject. 자연어 hint 아닌 *완성된 cfg snippet* 또는 *strategy switch 명시*. LLM weight 무시 가능성 줄임.

**MVP 2 recipe** (codex plan 리뷰 권장 — 4 recipe 보다 좁게 시작):

#### Recipe 1: `rss_post_id_from_link` (thisamericanlife targeted)

- **trigger**: attempt_history 의 fail key `post_id_unique` 또는 `post_id_stable_shape` 가 >= 2회
- **applies_to** (구조 신호 모두 만족):
  - `cfg.strategy == "httpx_html"`
  - `cfg.list.row_selector` matches `item|channel > item|entry|feed > entry` (RSS/Atom row pattern)
  - `digest.site_kind.kind in (rss, podcast, hybrid)` 또는 `feed_candidates` 에 validated XML 후보 1+
- **patch**:
  ```json
  "list.fields.post_id": [
    {"from": "css", "selector": "link", "text": true,
     "transform": [["strip"], ["strip_query_fragment"], ["regex_extract", "/([^/?#]+)/?$"]]}
  ]
  ```
- **text hint**: "RSS item 의 guid 가 불안정 ID — link path tail 사용. 정확한 transform 위 patch 그대로 박아라. 다른 selector 미세 변형 X."

#### Recipe 2: `spa_rendered_retry` (radiolab targeted, generic SPA)

- **trigger**: attempt_history 의 fail key `posts_nonempty` 또는 `title_nonempty` 가 >= 2회
- **applies_to**:
  - `digest.site_kind.kind == "spa_rendered"` AND `site_kind.confidence == "high"`
- **patch** (strategy switch only):
  - `cfg.strategy == "httpx_html"` 면 → `strategy = "playwright_html"` + `list.wait_selector` 기본값 (probe 의 top repeating pattern selector 추출)
  - 이미 `playwright_html` 이면 patch 없음 (text hint 만)
- **text hint**: "skeleton/loading row 가 server-rendered HTML 에 박혀있으나 진짜 row 는 hydration 후. wait_selector 가 *진짜 row* 까지 기다리도록 강화 — `a[href]` 단순 대신 *실제 title element* (h2/h3/.card-title 류) 명시. 진짜 selector 는 디지스트 의 html_repeating_patterns 중 *hydration 후* 등장하는 후보 사용."
- **주의**: `.radiolab-card` 같은 site-specific selector 박지 X — generic SPA hint 만. 회복 *보장 X*.

### 2b. 구현 위치 (B+C hybrid, prompt semantics 수정)

#### B. `_enrich_retry_feedback` 확장 (`generate/generator.py`)

- attempt N>=2 시 attempt_history + digest 보고 `_select_retry_recipes` 호출 → 적용 가능한 recipe list 반환
- recipe text hint 를 feedback text 끝에 별도 섹션 박음:
  ```
  ### 추천 수정 starting point
  반복 실패 (post_id_unique 2회+) → 다음 patch 적용한 시작점:
  [patched cfg JSON]
  
  이전 실패 config 가 아니라, 반복 실패 봉합용 candidate. 실제 digest 와 안 맞으면 조정하라.
  ```

#### C. retry loop 가 patched candidate 계산 (`generate/generator.py:generate_config_validated`)

- attempt N>=2 시 `_apply_recipe_patch(prev_cfg, recipes)` 호출 → patched candidate
- `build_retry_prompt(digest, prev_cfg, feedback, candidate=patched)` 같은 *별도 인자* 로 전달
- **`prev_cfg` 자체는 덮어쓰지 X** (R-H3 critical — prompt 의 "직전 실패 cfg" 문구와 모순 회피)

#### `build_retry_prompt` 시그니처 변경 (`generate/prompt.py`)

```python
def build_retry_prompt(
    digest: dict,
    prev_config: dict,
    feedback_text: str,
    *,
    starting_candidate: Optional[dict] = None,  # 신규
    max_html_chars: int = 120_000,
) -> str:
```

`starting_candidate` 있으면 prompt 안 별도 block (`### 추천 수정 starting point`) 박음. 없으면 기존 동작.

### 2c. 코드 변경 자리 요약

| 파일 | 변경 |
|---|---|
| `generate/generator.py` | `_FAIL_RECIPES` dict 신설 + `_count_fail_key`/`_select_retry_recipes`/`_apply_recipe_patch` helper + `_enrich_retry_feedback` 확장 + retry loop 의 candidate 계산 + `build_retry_prompt` 호출 변경 |
| `generate/prompt.py` | `build_retry_prompt` 에 `starting_candidate` 인자 + 별도 block 렌더 |
| `tests/probe_heuristics/test_retry_recipes.py` 신규 | recipe 선택 + patch 생성 + prompt 렌더 unit-test |

## 3. risk + 완화

codex plan 리뷰 R-H1~R-H13 정리:

| risk | severity | 완화 |
|---|---|---|
| R-H1 false positive | medium | applies_to 룰에 RSS 구조 신호 (site_kind + row_selector + validated feed) 결합 — recipe 1 의 조건 strict |
| R-H2 cascade fail | medium | link path tail 이 tracking/player URL 인 사이트 — recipe 적용 후 *post_id_unique 또 발생* 가능. 회복 vs 무한 cascade 모니터링 |
| **R-H3 prev_cfg patch 무시** | **critical** | **`prev_cfg` 덮어쓰기 X**. 별도 `### 추천 수정 starting point` block + 문구 명시 |
| R-H4 spa F enforcement | minor | 이번 plan 보류. retry-only override 만 (recipe 2) |
| R-H5 fail key 매칭 | minor | `attempt_history["fails"]` 가 이미 `c.name` (validation check 이름) — substring match X, exact match OK |
| R-H6 overfit | minor | 2 recipe 시작. fail pattern 추가 시 recipe 확장 |
| R-H7 recipe vs post_processor 충돌 | medium | recipe = prompt 단계 (LLM 한테 suggestion). post_processor = LLM 결과 *후* enforcement. 순서 안전 |
| R-H8 회복률 측정 | minor | fixture-only 검증 (unit-test recipe 선택 + patch 생성 + prompt 렌더). N100/LLM 안 필요 |
| R-H9 recipe hardcode | minor | 2 recipe 코드 hardcode OK. YAML 추출은 recipe count 증가 후 |
| **R-H10 dead patch key** | **critical** | `list.wait_selector_hint` 같은 가짜 key 박지 X. 실제 engine 읽는 key 만. recipe 2 의 wait_selector 는 *진짜 selector* 박음 (없으면 text hint 만) |
| **R-H11 radiolab fail key mismatch** | medium | recipe 2 trigger 에 `title_nonempty` 도 포함 (`posts_nonempty` 만 X) |
| **R-H12 article_body_len 너무 broad** | medium | 이번 plan 외. 별도 후속 — 구조 신호 (audio_share_host_detected.confidence=structural) 결합 후만 |
| R-H13 config pollution | medium | engine 모르는 키 (`wait_selector_hint` 등) 박지 X. prompt text + candidate block 만 |

## 4. 검증 절차 (fixture-only)

### 4a. unit-test (`tests/probe_heuristics/test_retry_recipes.py`)

각 recipe 별:
1. **trigger 매칭**: attempt_history fixture 로 fail key 2회+ 만들고 recipe 선택 함수 호출 → 매칭 확인
2. **applies_to 룰**: digest/cfg fixture 다양 (RSS / non-RSS / site_kind 분기) → 정확 매칭 확인
3. **patch 생성**: prev_cfg + recipe → patched candidate 정확
4. **prompt 렌더**: build_retry_prompt 호출 → 별도 block 박힘 확인

### 4b. 회귀

- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS
- 기존 251 configs register --config 회귀 0 (probe_smoke stage 3)
- `test_site_kind.py` 16 case PASS

### 4c. 시뮬레이션 (선택)

`generate/generator.py` 단위에서 thisamericanlife/radiolab probe artifact + mock LLM 으로 retry 3회 시뮬 → recipe inject 확인. 단 실제 LLM 호출 X.

### 4d. 진짜 회복 검증 (다음 세션 이후)

다음 podcast batch 또는 thisamericanlife/radiolab 의 N100 register --force --reuse-probe — recipe inject 후 *진짜 자동생성* 되는지. N100 LLM call 비용 — 다음 세션 마지막 1-2건만.

## 5. 다음 세션 진입 가이드

### 5a. 컨텍스트 빠르게 받는 법

1. 이 plan 문서 + `docs/cases/_session_retro_2026-05-24_podcast.md` §7 읽기
2. plan 리뷰 결과 = `output/codex_generic_podcast-h-plan-review-task_prompt.result.md` 읽기
3. 현재 `_enrich_retry_feedback` 구조 = `generate/generator.py:29~128`
4. 현재 `build_retry_prompt` = `generate/prompt.py:99`
5. 현재 site_kind 구조 = `engine/digest.py:classify_site_kind` (commit `04817bf`)

### 5b. 첫 명령 (다음 세션)

```bash
# 1. 현재 fail key 종류 확인 (validation check name)
grep -n "name=" engine/validate.py probe/_contract.py | head -30

# 2. attempt_history fail 키 형식 확인
python -c "
import sys; sys.path.insert(0, '.')
from generate.generator import _enrich_retry_feedback
# attempt_history fixture 만들어서 호출
"

# 3. test_retry_recipes.py 작성 (fixture-only)
# 4. _FAIL_RECIPES + helper + retry loop 변경
# 5. probe_smoke PASS 확인
# 6. (선택) thisamericanlife N100 --force --reuse-probe 진짜 회복 확인
```

### 5c. 작업 ALLOW-LIST

- `generate/generator.py`
- `generate/prompt.py`
- `tests/probe_heuristics/test_retry_recipes.py` (신규)
- `tests/probe_heuristics/test_site_kind.py` (회귀 검증)

### 5d. 작업 금지

- `prompts/config_writer.system.txt` 변경 X (이번 plan 영역 아님 — 이미 박힌 RSS post_id 룰 + spa_rendered hint LLM 무시가 *문제*. prompt 추가 X, recipe 강제 inject)
- `scripts/register.py:_make_cfg_post_processor` 변경 X (post-LLM 영역 — recipe 와 별개)
- `engine/digest.py:classify_site_kind` 변경 X (site_kind 분류 자체는 정확)
- `configs/host_*.json` 변경 X
- N100 ssh restart / 배포 — 마지막 단계만 (recipe 박힌 후 회복 검증 1-2건)
- git commit / push — Claude 가 직접 (codex 위임 시 worktree)

## 6. 후속 (이번 plan 외 — 추가 plan 필요)

- **link_rel validate** (dotnetrocks 가짜 RSS) — `register._build_digest` 의 `rss_feed_urls` 의 첫 candidate fetch + validate 박기. 1 fetch 비용
- **article_body_len recipe** — 외부 host / audio_share 구조 신호 결합 (R-H12)
- **시간 budget** — `discover_feeds` 의 fetch 누적 — per-host concurrency limit
- **recipe count 증가 후 YAML 추출** — recipe 4+ 시 `prompts/retry_recipes.yaml`

## 7. 참조

### commit chain (이전 작업)

- `32d036e` chunk C — audio share structural
- `219fb18` chunk D — SKILL guards + feed validation
- `4cec12e` retro 작성
- `f487b54` F1 — R-D1/R-D4/R-C1 봉합
- `04817bf` F2 — site_kind enum
- `af41a2e` junk row filter
- `e638bfe` link_rel med
- `8610d9c` backfill 순서
- `4175415` G merge + retro 광신 + oxide improved
- `<TBD>` H — retry recipe MVP (이 plan)

### 코드 위치

- `generate/generator.py:29~128` — `_enrich_retry_feedback`
- `generate/generator.py:195+` — `generate_config_validated` retry loop
- `generate/prompt.py:99` — `build_retry_prompt`
- `engine/digest.py:classify_site_kind` — site_kind 분류
- `scripts/register.py:_make_cfg_post_processor` — F-layer enforcement (post-LLM)

### test 위치

- `tests/probe_heuristics/test_site_kind.py` — 16 case
- `tests/probe_heuristics/test_audio_share_host.py` — audio share
- `tests/probe_heuristics/test_feed_candidate_validation.py` — feed validate
- `tests/probe_heuristics/test_retry_recipes.py` — *신규 작성 자리*

### 진짜 회복 검증 URL

- thisamericanlife: `https://feeds.thisamericanlife.org/talpodcast` (진짜 RSS, post_id_unique fail)
- radiolab: `https://radiolab.org/podcast` (Nuxt SPA, posts_nonempty/title_nonempty fail)
- (참고) oxide: `https://oxide.computer/podcast/rss.xml` (이미 자동생성 됨, 회귀 검증용)
