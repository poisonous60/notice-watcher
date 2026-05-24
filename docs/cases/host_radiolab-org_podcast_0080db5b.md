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
