---
slug: host_atlus-co-jp_news_14abbfb2
url: https://www.atlus.co.jp/news/
status: "✅ improved — `_heterogeneous_hub_check` 가 정적 pagination + announcement-tab 으로 escape"
outcome: improved
date: 2026-05-26
fix_layer: C+F
failure_keys: [heterogeneous_hub_check, pagination_hints_path_segment, article_shape_underscore]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/register.py]
tags: [batch-2026-05-24-games-jp, false-reject, pagination, heterogeneous-hub-gate]
---

## 신호

`_heterogeneous_hub_check` (gen_fail post-mortem 게이트) 가 *announcement-tab + 정적 pagination 보유* 사이트를 false-reject 한 패턴 2종.

같은 2026-05-24-games-jp batch 의 같은 fail_reason — §0c-0 1번 (agentic 자리 박기) 적용.

| trigger slug | URL | 정적 신호 | OLD 결과 | 원인 |
|---|---|---|---|---|
| host_atlus-co-jp_news_14abbfb2 | https://www.atlus.co.jp/news/ | `/news/page/{2,3,4,163}` + `<a href="/news/37063">` 단일 + p-ch.jp 외부 host 카드 다수 | REJECT — clean article cluster 0종 | 내부 article cluster 가 작고 외부 host 카드가 다수 → 게이트가 article 신호 없다고 판정 |
| host_fate-go-jp_news_92f8d1f5 | https://www.fate-go.jp/news/ | cluster cc=10 `/{n}/05/2026_grand_caster_cp/` (underscore 슬러그) + `<div class="pager"><a href="/page/2/">次へ »</a></div>` | REJECT — clean article cluster 0종 | `is_article_shape` 가 underscore 슬러그(`2026_grand_caster_cp`) 를 dash-only 매처라 article 로 인식 못함 → nav 로 분류 |

## fix layer 매핑

§6 6 자리 위에서부터 — (E)/(D) 자리 없음, **(C) probe digest 신호** + **(F) 게이트 escape** 가 자리.

### (C) `probe/extract.py:pagination_hints` 확장 — path-segment + pager-class wrapper

- `_PATH_PAGE_RE = re.compile(r"/page/(\d+)/?$")` 추가 (path-segment style pagination, atlus 류 정적 archive)
- `_pagination_path_template(url)` helper (`/page/N` → `/page/{page}`)
- `pagination_hints` 본체 확장: html anchor 스캔 시 path_segment 도 누적 → ≥2 distinct page numbers OR ancestor class `~="pager|pagination|paging|page-nav"` 면 emit
- `kind: "path_segment"` 추가, 기존 `kind: "query_param"` 와 공존

### (F) `scripts/register.py:_heterogeneous_hub_check` 두 곳 보강

1. **announcement-tab + pagination escape (top)**: URL path 에 `/news/|/notice/|/announcement/|/topics/|/info/|/press/|/release/|/notification/|/whatsnew/|/news-and-events/` segment AND `pagination_hints` 비어있지 않으면 즉시 `return None` (사이트가 *명시적으로* 공지 탭 + 페이지네이션 보유 = explicit board 의도)
2. **`is_article_shape` underscore 지원**:
   - `slug_shape = len>=8 AND (count('-') + count('_')) >= 2`
   - `id_shape = ... .replace(".","").replace("_","").isalnum() ...`
   - JP/CMS 의 `2026_grand_caster_cp` 같은 underscore 슬러그 인식 (fate-go 류)

## 회귀 검증 (실 artifact replay — §5 step 1b)

OLD vs NEW (현 register.py + probe/extract.py 로 디지스트 재계산):

```
==== host_atlus-co-jp_news_14abbfb2 https://www.atlus.co.jp/news/
  OLD (no pagination): clean article cluster 0종 — content 행이 반복되는 게시판 본질 신호 없음 (REJECT)
  NEW (pagination=1):  OK — escape (announcement-tab `/news/` + path_segment `/news/page/{page}`)

==== host_fate-go-jp_news_92f8d1f5 https://www.fate-go.jp/news/
  OLD (no pagination, dash-only is_article_shape): clean article cluster 0종 (REJECT)
  NEW (pagination=1, underscore-aware): OK — article cluster cc=10 `/{n}/05/2026_grand_caster_cp/` 가 underscore 슬러그라 article 인식 → nav_max=0 → board OK

==== root URLs (false-positive guard)
  host_gemdrops-co-jp_root_b8e15fb3 (https://www.gemdrops.co.jp/): REJECT 유지 — pagination=0, path `/` 에 announcement segment 없음, escape 미적용 ✅
  host_yostar-co-jp_root_03c562b4 (https://www.yostar.co.jp/):     REJECT 유지 — 같은 이유 ✅
```

probe_smoke stage 3+5: PASS 1520 FAIL 0 (configs validate 267/267, heuristic units 1252/1252, +14 새 path_segment cases).

## 일반화 후보 / 보류

이번 PR 에 같이 들어간 패턴 외 미해결:

- **SPA shell (granbluefantasy.jp/news/)** — SvelteKit `_app/immutable/*` 번들만 정적 HTML 에 있고 카드/페이지네이션 모두 JS 렌더 후 DOM. C/F-layer 정적 신호로 회복 불가 — playwright_html 수동 config 트랙. **보류 (deferred_heuristics)** — `is_spa_shell_render_track`: `<script src=_app/immutable|_next/static|_nuxt>` ≥3 + 정적 same-host repeating pattern cc≥5 == 1 + 그 1개 path 가 base URL 과 같음 → playwright re-probe 권장. 1건째 (granblue) 라 보류. 같은 패턴 1건 더 + safety AND 가능할 때 lift.
- **announcement-tab segment classifier prior (A-layer)** — `prompts/classify.system.txt` 에 "URL 에 `/news/`·`/notice/` 등 announcement-tab segment = index 사전확률 강화" 룰 추가 검토. 현재 false-reject 4종 (`barks.jp/news/` 등) 은 classifier content veto — 별도 PR 후보. 이번 batch 에서 escape 게이트 자체로는 cover X (gen_fail post-mortem 게이트만 손댐).

## 일반화 트리거

`_deferred_heuristics.md` 의 `is_spa_shell_render_track` 1건 등록. 같은 패턴 1건 더 들어오면 lift.
