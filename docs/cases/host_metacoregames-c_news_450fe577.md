---
slug: host_metacoregames-c_news_450fe577
url: https://www.metacoregames.com/news/
status: ✅ handcrafted
outcome: handcrafted
date: 2026-05-27
fix_layer: F
failure_keys: [panda_css_atomic_class_huge_selector, spa_hydration_misdetected_as_static, register_audit_violation]
config_strategy: playwright_html
engine_files_touched: []
adapters_changed: []
tags: [panda-css, chakra-v3, atomic-css, spa-hydration, handcrafted, batch-2026-05-24-games-mobile-casual]
requested_by: user
vocab_candidates: []
---

# Metacore Games /news/ — Panda CSS atomic class + SPA hydration

## 배경

Catalog `2026-05-24-games-mobile-casual` batch 의 1 sites. 두 단계 fail:

1. **1차 (BUG rc=-4)**: agentic register 가 AUDIT_FAIL — `agent wrote outside tmpdir`. 5 violations 의 파일이
   정확히 dev box 같은날 push commit 의 수정 파일과 일치 (race condition). audit-race-guard fix (commit f1f8010)
   가 `_audit_diff` 에 git HEAD snapshot + diff name-only 비교 박아 영구 게이트.

2. **2차 (gen_fail rc=1)**: race-guard 통과 후에도 agent max_cycles. 같은날 박은 Tailwind dot+colon escape
   feedback fix 도 적용됐지만, 이 사이트의 selector 가 *Panda CSS atomic-class* (`>600 chars`) 라 escape
   규칙만으로 부족.

## 진단

- live: `curl -sL https://www.metacoregames.com/news/` → 308 → `metacoregames.com/news/` → 308 → `/news` (no slash).
  실재 marketing news board. Next.js + Panda CSS (Chakra v3 ecosystem) stack.
- probe diagnosis: `verdict: 정적 HTTP로 충분` (잘못된 verdict — 실측 검증 결과 ↓).
  - `s1.H2.html` (raw httpx, len=1035052) → `feed-block-items-grid` shell 존재, anchor 0개.
  - `s1.H4.html` (raw httpx variant) → 동일.
  - `list.html` (playwright render, len=1132404) → anchor **12개** (12 row).
  - 즉 정적 응답은 SPA shell 만 옴. 실 컨텐츠는 hydration 후에만. probe verdict 가 잘못 판정.
- probe row cluster 첫번째: 600+ char Panda CSS atomic-class chain:

  ```
  div.d_grid.cg_defaultGap.rg_d.36.ai_start.grid-tc_1fr_1fr_1fr.largeMobileDown:px_pageMargin.
  largeMobileDown:grid-tc_1fr_1fr.largeMobileDown:rg_m.24.mediumMobileDown:grid-tc_1fr.
  feed-block-items-grid > article.d_grid.grid-tc_1fr.m_0_auto.gap_token(spacing.d.24)
  .ai_center.pos_relative.w_100%.[&.hide]:d_none.largeMobileDown:rg_m.16
  .[&_img]:bfv_hidden.[&_img]:trf_scale3d(1,1,1)_translate3d(0,0,0).
  [&_img]:trs_transform_token(durations.regular).[&_img]:motionReduce:trs_none!. ... .card-small
  ```

  SKILL §3 명시 anti-pattern: `class 가 [, :, / 포함하면 박지 마라`. bracket-arbitrary `[&_img]:trf_scale3d(...)`
  + responsive variant `largeMobileDown:px` + 숫자 클래스 `rg_d.36` + token call `gap_token(spacing.d.24)`
  4종 다 등장. escape 규칙 만으로 agent 가 cluster verbatim 사용 불가능.

## Track B 6-layer audit

- **E** schema 거부: hit — `_check_css_selector` 가 NotImplementedError 잡음 (이미 강화됨, commit f1f8010).
- **D** retry feedback: hit — 같은 commit 에서 dot+colon escape feedback 보강. 단 *bracket-arbitrary* `[&_*]:`
  는 다루지 않음. 1-case 라 보강 X.
- **C** probe digest 신호: miss — probe 가 거대 selector verbatim 캡쳐. 일반화 후보: cluster.selector
  >250 chars OR `[` 포함 시 simplified fallback selector (parent + tag + URL prefix filter) 동시 emit.
  **1-case 라 deferred_heuristics.md 등록**.
- **B** few-shot: miss — Panda CSS / Chakra v3 example config 없음. 단발 1건.
- **A** system 규칙 추가: hit (이미 commit f1f8010 + SKILL §3 가 `[, :, / 포함 class 박지 마라` 명시) —
  agent 가 이 룰 보고도 cluster verbatim 시도. 1-case 라 추가 보강 보류.
- **F** 엔진 코드: hit (audit race guard) — 이미 박힘 (commit f1f8010).

추가 박을 자리:
- **C-layer 일반화 후보** (`probe_simplify_huge_atomic_class_selector_with_url_pattern_fallback`) — deferred_heuristics 등록.
- **probe verdict 정확화 (raw httpx anchor count 0 → playwright 필요 자동 권장)** — 다른 deferred 후보
  `is_spa_shell_render_track` 와 같은 패밀리. metacoregames 가 그 후보의 2nd instance 신호 (정적 HTML
  feed-block-items-grid shell + raw httpx 0 anchor + 렌더된 list.html 12 anchor). granbluefantasy 1건 +
  metacoregames 1건 = 2건. 단 granbluefantasy 는 SvelteKit, metacoregames 는 Next.js+Panda — *프레임워크 다름*
  이지만 *행동 동일* (shell + hydrated rows). 2건 누적 트리거 도달 — 다음 chunk 또는 batch 에서 lift 검토.

## fix

`configs/host_metacoregames-c_news_450fe577.json` 신규 — playwright_html strategy.

- list.url_template: `https://www.metacoregames.com/news/`
- list.wait_selector + row_selector: `div.feed-block-items-grid a[href^='/news/']` (descendant,
  not direct child — featured 1건은 `<a><article>...</article></a>` 구조, 나머지 11건은 `<article>...<a></a></article>` 구조 mix)
- post_id: regex_extract `^/news/([^/?#]+)/?`
- url: urljoin + strip_query_fragment
- title: h3 text
- article: fetch_kind html, content selector `main`, enrich h1 title + `time[datetime]` published_at

smoke test:

```
list: 10
  metacore-plans-organizational-restructur 'Metacore Plans Organizational Restructuring to Foc'
  strengthening-technology-and-engineering 'Strengthening technology and engineering leadershi'
  ... (10 unique)
article body chars: 44715, title OK, pub: 2026-05-05T00:00:00+00:00
```

## ship evidence

batch 2026-05-24-games-mobile-casual 처리 도중 사용자가 "https://metacoregames.com/news 처리할 수 있었으면
좋겠는데" verbatim — slug URL 직결 + 즉시 작동 요청. Track A 진입 조건 (b) 충족.

## 일반화 후보 (deferred)

1. **probe_simplify_huge_atomic_class_selector_with_url_pattern_fallback** (C-layer) — `_deferred_heuristics.md`
   append. 트리거: 같은 패턴 1건 더 (Panda CSS / Chakra v3 / Park UI / atomic-css framework 사이트).
2. **probe_verdict_raw_anchor_zero_auto_promote_render** — `is_spa_shell_render_track` deferred 와 통합 후보.
   metacoregames 가 2nd instance. 다음 chunk 또는 batch 에서 검토.
