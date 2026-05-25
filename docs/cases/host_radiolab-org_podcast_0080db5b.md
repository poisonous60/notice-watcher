---
slug: host_radiolab-org_podcast_0080db5b
url: https://radiolab.org/podcast
status: 🧩 수동 config — Nuxt skeleton row 대신 hydrated Radiolab episode card를 기다려 title/url 추출
outcome: handcrafted
date: 2026-05-24
failure_keys: [title_nonempty, skeleton_rows, nuxt_hydration]
fix_layer: F
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [radiolab, podcast, nuxt, playwright-html, hydrated-card]
requested_by: podcast-batch-20260524
---

## 무엇이 일어났나

대상 URL:

```
https://radiolab.org/podcast
```

batch 실패는 `title_nonempty`였다. 기존 후보는 `div.grid.justify-content-center > div.col-12.mb-6` 계열 row에서 URL은 잡았지만 title이 5/5 빈 문자열이었다.

로컬 worktree에는 probe artifact가 없어서 N100에서 `output/probe/host_radiolab-org_podcast_0080db5b/`만 read-only로 가져와 확인했다. N100 코드나 서비스는 수정하지 않았다.

## 원인

`output/probe/host_radiolab-org_podcast_0080db5b/list.html`의 반복 후보:

```
div.grid.justify-content-center > div.col-12.sm:col-6.lg:col-4.mb-6
```

이 row 12개는 실제 episode 카드가 아니라 skeleton이었다.

snippet 핵심:

```html
<div class="recent-episodes-skeleton" paginate="true">
  <div class="grid justify-content-center">
    <div class="col-12 sm:col-6 lg:col-4 mb-6">
      <div style="width:100%;height:1rem;" class="p-skeleton p-component card" aria-hidden="true"></div>
    </div>
  </div>
</div>
```

Nuxt bundle `Episodes.f18b711b.js`는 `https://api.wnyc.org/api/v3/channel/shows/radiolab/recent_stories/{page}?limit=...`를 호출한 뒤 `n.attributes.title`과 `n.attributes.slug`로 `.radiolab-card` DOM을 만든다. 즉 `h2`가 비어 있던 게 아니라, 실패 selector가 hydrated card가 아닌 loading shell을 row로 잡은 것이다.

## 해결

strategy는 `playwright_html`로 유지했다. N100 headless 환경을 깨지 않도록 `headless: false`는 넣지 않았다.

row selector:

```
div.radiolab-card.v-card
```

wait selector:

```
div.radiolab-card.v-card .card-title-link .h2
```

title fallback:

```
.card-title-link .h2
a.card-title-link[aria-label]
```

url/post_id는 같은 `a.card-title-link`의 `href`를 사용한다. `post_id`는 `/podcast/<slug>` tail을 뽑고, `url`은 `urljoin`으로 절대 URL화한다.

article body는 `main .html-formatting`을 우선 사용하고, 없으면 `main`, `body`로 fallback한다.

## 회귀 검증

in-memory `make_adapter` 실행 결과:

```
posts 5
6808128dfafb25dbf298758e | Worth | https://radiolab.org/podcast/6808128dfafb25dbf298758e | 5월 22, 2026
your-friendly-neighborhood-hookworms | Your Friendly Neighborhood Hookworms | https://radiolab.org/podcast/your-friendly-neighborhood-hookworms | 5월 15, 2026
the-bad-show | The Bad Show | https://radiolab.org/podcast/the-bad-show | 5월 8, 2026
what-is-a-pig-worth | What is a Pig Worth? | https://radiolab.org/podcast/what-is-a-pig-worth | 5월 1, 2026
forests-on-forests | Forests on Forests | https://radiolab.org/podcast/forests-on-forests | 4월 24, 2026
article_len 2752
```

## 일반화 검토

- 2a platform recognizer: X. Radiolab/WNYC API와 card class naming은 사이트 전용이다.
- 2b `--article-url`: X. article URL 오인이 아니라 skeleton row를 잡은 title extraction 문제다.
- 2c probe heuristic: 보류. “skeleton row를 후보에서 낮추기”는 가능하지만 이번 chunk allow-list 밖인 probe 수정이 필요하다.
- 2d probe bug: X. `list_candidates.json`에 skeleton 후보가 나온 것은 현재 probe 산출물 기준 사실이다. selector 선택이 문제였다.
- 2e config: O. hydrated card를 기다리는 단일 사이트 config가 가장 작은 변경이다.

일반화 안 되는 이유: 실제 목록 API endpoint, `attributes.title`/`attributes.slug`, `.radiolab-card` 구조가 Radiolab 사이트 전용이다.

## 자가 점검 (§6)

1. **자리**: F. 새 engine 코드는 없지만, 단일 사이트 수동 config로 자동 생성 실패를 우회한 handcrafted fix다.
2. **이전 케이스**: 이번 작업에서는 allow-list 밖 index/DB query를 실행하지 않았다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: config schema validation, `make_adapter` list/article fetch, `register.py --config`, `probe_smoke --stage 3 --stage 5`.
5. **outcome=handcrafted**: selector와 wait 조건을 손으로 고른 단일 사이트 config다.
6. **fixture**: 새 strategy/engine 변경이 아니므로 fixture 추가 없음.
7. **트랙 B 0건 사유**: 위 일반화 검토 참조.

---

## 2026-05-25 추가 — D-layer recipe 시도 + 한계

`docs/cases/_plan_retry_recipes_2026-05-25.md` 의 Recipe 2 (`spa_rendered_retry`) 가 이 사이트
대상으로 만들어짐. trigger = `posts_nonempty`/`title_nonempty` 반복 + site_kind=spa_rendered/high.
N100 register --force --reuse-probe --max-attempts 5 결과:

```
시도 1-5 모두: FAIL — 하드 실패: posts_nonempty(0건)
```

자동 회복 안 됨. handcrafted config 그대로 보존 (register 가 LLM 자동 등록 다 실패 시 기존
config 안 덮어씀).

### 왜 D-layer 만으로 안 됨

LLM 이 시도 1 부터 strategy=playwright_html 박음 (Recipe 2 의 patch 가 strategy switch 만이라
이미 그 strategy 면 patch no-op). text hint *는* 박혀 LLM 한테 진단 정보 전달 됐지만 진짜
row selector (`.radiolab-card .card-title-link .h2`) 못 추측:

- 진짜 selector 는 *hydration 후* DOM 에만 존재.
- probe 의 정적 list.html 에는 `.radiolab-card` 등 component class 가 **inline `<style>` 의
  CSS rule** 안에만 박혀있음 — DOM element 로는 없음.
- `engine/digest.py:clean_html` 가 `<style>` 다 제거 → LLM prompt 에 component class 단서 X.
- probe 의 `html_repeating_patterns` 후보는 skeleton row (`div.col-12.mb-6`) 만 잡음 — top
  candidate 인데 _pick_spa_wait_selector 의 nav/skeleton blocklist 에 안 걸려 함정.

### 후속 plan 후보 (이번 plan 외)

1. **digest CSS component class extract** — `engine/digest.py:build_digest` 가 raw list.html 의
   `<style>` 블록 또는 fetched CSS 에서 자주 등장하는 component class 추출 → 새 키
   `list_candidates.css_component_classes`. Recipe 2 의 `_pick_spa_wait_selector` 가 이 후보도
   참고. 가능한 false-positive: nav/footer/utility class.
2. **probe hydration capture** — 정적 httpx 외 playwright_html 로 hydrated DOM 캡처 → 별도
   `list.hydrated.html` 파일. digest 가 별도 키로 LLM 에 전달. 비용 큼.
3. **skeleton row blocklist 확장** — `validate.py` 또는 probe 의 row pattern 후보 점수에서
   `*-skeleton`, `loading`, `placeholder` 류 class reject. probe artifact 의 false
   "top repeating pattern" 정정.

handcrafted config (이 case §해결) 가 정답인 사이트. recipe 가 모든 SPA 회복 가능한 건 아님 —
정보 부족 사이트는 hand-config 필요.

---

## 2026-05-25 추가 — probe/digest 강화 3 option 적용 + 부분 회복

`docs/cases/_plan_radiolab_probe_digest_2026-05-25.md` (codex 리뷰 통과) 3 option 박음:

1. **CSS component class extract** (`engine/digest.py:_extract_css_component_classes`) —
   raw HTML 의 `<style>` rule 에서 component class 추출. utility/chrome/generic blocklist
   적용 후 top 8 by frequency.
2. **probe hydration extra wait** (`probe/fetch_headless.py:_has_spa_hydration_marker`) —
   strict SPA marker (Nuxt/Next/Vuex) 발견 시 추가 1500ms quiet 대기 후 capture.
3. **skeleton descendant reject** (`probe/extract.py:_row_has_skeleton_descendant`) — row
   의 첫 10 자손 class 에 skeleton/loading 박혔으면 후보 reject.

### 효과

Radiolab probe 재실행 결과:

```
=== top html_repeating_patterns ===
   head > link child= 58 ...
   head > meta child= 23 ...
   head > style child= 17 ...
   g > path.st0 child= 6 ...
=== css_component_classes (top 8) ===
   radiolab-card rule_count= 123 co= ['v-card', 'card-blurb', 'card-title-link']  ← 진짜 row!
   v-card rule_count= 123 co= ['radiolab-card', 'card-blurb', 'card-title-link']
   card-blurb rule_count= 75 ...
   card-title-link rule_count= 27 ...
```

- ✅ skeleton container (`div.col-12.mb-6`) 가 html_repeating_patterns top 에서 사라짐
- ✅ css_component_classes top 1 = `radiolab-card` (rule_count 123)
- ✅ N100 register attempt 5 의 cfg = `row_selector: .radiolab-card`, `wait_selector:
  .radiolab-card, .card-title-link, .card-blurb` — **LLM 이 진짜 selector 박음** (CSS extract
  + _pick_spa_wait_selector fallback 효과)

### 그러나 0건 — 남은 한계 (별도 plan 필요)

attempt 5 의 LLM cfg vs handcrafted 비교:
- LLM url: `https://radiolab.org/podcast`
- handcrafted url: `https://radiolab.org/podcast?page={page}`

Radiolab Nuxt 가 `?page` query 없는 URL 에서 podcast cards 안 그림 (페이지네이션 hint 필요).
또는 `/podcast` 자체가 마케팅 redirect 페이지 (probe `S4.click` 결과 = `radiolab.org/the-lab`
로 라우팅됨이 그 증거).

= 사이트 별 URL pagination param 처리 — 일반화 어려움. handcrafted config (위 §해결) 가 정답
유지. recipe + probe 강화로 *selector 추측은 봉합* 됐지만 *URL hint* 는 LLM 추가 휴리스틱
필요 (별도 plan 후보).

### commit chain

- `19e1815` probe/digest 3 option (CSS extract + SPA wait + skeleton reject)
- `809625a` URL pagination heuristic (HTML anchor + HAR XHR + `_contract.py` schema + prompt)
- `9a25cf3` pagination_hints rtype fallback (HAR `_resourceType` 안 박힌 경우) + SPA quiet_ms 3000ms

---

## 2026-05-25 추가 — URL pagination heuristic + 추가 wait 적용 후 한계

`probe/extract.py:pagination_hints` (commit 809625a) + rtype fallback + quiet_ms 3000ms
(commit 9a25cf3) 적용 후 Radiolab probe 재실행:

```
=== pagination_hints ===  (빈 list)
=== HAR (total 49 entries) ===
  49 entries 중 데이터 fetch URL 0건 — Nuxt JS chunks (entry/components/Episodes/VCard
  등) + GA collect 만 있음. 진짜 API fetch `api.wnyc.org/...recent_stories` 가 HAR 에
  안 잡힘.
```

### 진짜 root cause — probe headless 환경 limit

Radiolab Nuxt 의 client-side fetch (`api.wnyc.org/...recent_stories`) 가 chunks 로드 →
hydration → fetch 순서로 실행됨. **3000ms quiet 후 capture 까지도 fetch trigger 안 됨**.
가능성:
- chromium headless 환경의 navigator/UA 차이로 사이트가 lazy hydration
- 진짜 fetch 까지 8-10초 + user scroll 등 trigger 필요
- Cloudflare/anti-bot 류 차단 (Radiolab 은 명시 보이지 X)

### LLM register 결과도 동일

`?page=1` URL 명시 + max_attempts 5 도 5 시도 다 posts_nonempty(0건). LLM 박은 cfg:
- strategy=playwright_html, row_selector=`a.card-title-link`,
  wait_selector=`a.card-title-link, .card-title-link`, timeout=15s
- 정확한 selector 박지만 *engine 의 playwright_html strategy 도 hydration 후 DOM 못 잡음* —
  probe headless 와 같은 환경 한계.

### 결론

- ✅ 인프라 (CSS extract + skeleton reject + SPA wait + pagination heuristic) 정확히 작동
- ✅ LLM 이 `radiolab-card` 진짜 component class 추측 (CSS extract 효과)
- ❌ chromium headless 자체가 Radiolab Nuxt 의 진짜 fetch trigger 못 일으킴 — 모든 cfg 0건

handcrafted config (이 case §해결) 가 *bot polling 환경에서 작동* 하는 것은 별도 environment
(폴링 서비스의 playwright 환경 vs probe `--lite` 환경) 차이 가능성. 또는 그 시점 (2026-05-24)
의 사이트 상태 — 현재 시점에서는 handcrafted 도 회복 보장 X.

진짜 fix 후보 (별도 plan):
- probe `wait_for_load_state("networkidle", timeout=8000)` 추가
- user interaction simulate (scroll/click) — invasive
- SPA marker 검출 시 *networkidle* + DOM mutation 양쪽 기다림
