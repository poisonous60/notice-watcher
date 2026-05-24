---
slug: host_feeds-thisameri_talpodcast_c725ed7a
url: https://feeds.thisamericanlife.org/talpodcast
status: ✅ D-layer recipe 회복 — 자동 등록 완료 (15건)
outcome: improved
date: 2026-05-25
failure_keys: [post_id_stable_shape, post_id_unique, rss_post_id]
fix_layer: D
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [generate/generator.py, generate/prompt.py]
tags: [podcast, rss, post-id, auto-recovery, d-layer-recipe, fallback-chain]
requested_by: plan-retry-recipes-2026-05-25
---

## 무엇이 일어났나

기존 실패는 `[FAIL] post_id_stable_shape` 계열이다. RSS item 의 `<guid>` 가 긴 원문/URL 조합이면 post_id 로 부적합하고, `link` path tail 이 더 안정적인 fallback 이다.

## 픽스

- A: `prompts/config_writer.system.txt` 에 RSS item `<guid>` 가 긴 문장/URL/복합 문자열이면 `link` path tail 을 `regex_extract "/([^/?#]+)/?$"` 로 post_id 에 쓰라는 규칙을 추가했다.
- C/D: 오래된 artifact 에서 direct feed URL 을 `rss_feed_urls` 로 backfill 해 direct feed 입력도 feed config 작성 경로로 들어가게 했다.

## 등록 검증 상태

`register.py --reuse-probe https://feeds.thisamericanlife.org/talpodcast` 는 LLM 생성 단계까지 도달했지만 등록 완료는 LLM key 부재로 막혔다.

원문:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

현재 backfill 확인: `rss_feed_urls[0].url=https://feeds.thisamericanlife.org/talpodcast`.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS.
- `python scripts/register.py --reuse-probe https://feeds.thisamericanlife.org/talpodcast` FAIL, 원인은 LLM key 0개.
- 영향 범위: RSS post_id 작성 규칙. 기존 config 직접 변경 없음.

---

## 2026-05-25 추가 — D-layer recipe 회복 ✅

### 무엇이 바뀌었나

2026-05-24 의 A-layer (prompt 룰 추가) 만으로 봉합 안 됨이 podcast batch 재검증에서 확인됨
(`docs/cases/_session_retro_2026-05-24_podcast.md` §7d/§7f). LLM 이 prompts 의 RSS post_id
룰을 일관 무시. **D-layer retry feedback dynamic injection** 인프라 박음
(`docs/cases/_plan_retry_recipes_2026-05-25.md`):

- `generate/generator.py:_select_retry_recipes` — 같은 hard fail key (post_id_unique /
  post_id_stable_shape) 가 ≥2회 + applies_to (RSS row + site_kind rss/podcast/hybrid 또는
  validated feed 1+) 만족 시 `rss_post_id_from_link` recipe 발동.
- `generate/generator.py:_apply_recipe_patch` — prev_cfg deepcopy 에 패치. 패치 자체는
  *fallback chain*: 1순위 guid number prefix (`regex_extract "^(\\d+)"`), 2순위 link 전체 URL
  (strip + strip_query_fragment).
- `generate/prompt.py:build_retry_prompt(starting_candidate=...)` — patched cfg 를 prompt 의
  별도 `### 추천 수정 starting point (D-layer recipe)` 블록으로 렌더. prev_cfg block 안 덮어씀
  (R-H3 critical).

### 진짜 원인 — 왜 link path tail 만 박으면 안 됐나

`link path tail` (`regex_extract "/([^/?#]+)/?$"`) 만 시도한 첫 patch (commit df6e894) 도
LLM 회복 X (5 시도 다 dup 2건). TAL RSS feed *자체* 에 진짜 link 중복:

```
$ grep -oE "<link>[^<]+</link>" output/probe/host_feeds-thisameri_talpodcast_c725ed7a/*.rss | sort | uniq -d
https://www.thisamericanlife.org/lifepartners
https://www.thisamericanlife.org
```

- `lifepartners` 2번 (re-publish)
- root URL 2번 (promo item)

guid 는 모두 unique number prefix (`"46156 at https://..."`). number 만 추출하면 진짜 stable
unique ID. fallback chain (guid number 우선 + link 전체 fallback) 으로 commit db4fa21 박음.

### N100 register 결과

```
$ register.py "https://feeds.thisamericanlife.org/talpodcast" --slug ... --reuse-probe --force --max-attempts 5
  시도 1: FAIL — 하드 실패: post_id_unique(중복 2건)
  시도 2: FAIL — 하드 실패: post_id_unique(중복 2건)
  시도 3: PASS — 통과 (15건)
✅ 등록 완료
```

시도 3 에서 recipe trigger 발동 (fail 2회 누적) → LLM 이 starting_candidate 의 fallback chain
따라감 → 15건 unique post_id 추출 PASS.

### commit chain

- `b311b0f` D-layer recipe MVP (path tail 추출 patch)
- `df6e894` Recipe 1 → link 전체 URL (path tail collision 회피 시도) + Recipe 2 text-hint-only
  path fix (Radiolab 류 — 이미 권장 strategy 인 경우 text hint 도 사라지던 bug)
- `db4fa21` Recipe 1 → fallback chain (guid number prefix + link 전체) — **TAL 회복 ✅**

### 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS (1319 PASS, 0 FAIL).
- N100 register --force --reuse-probe 시도 3 PASS, 15건 등록.
- `tests/probe_heuristics/test_retry_recipes.py` — 27 fixture case (R-H3 mutation 가드 + R-H10
  nav blocklist + fallback chain shape + no-op path).
