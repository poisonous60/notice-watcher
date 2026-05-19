---
slug: host_vimeo-com_root_c6a102cf
url: https://vimeo.com/
status: ❌ 자동 등록 실패 (tailwind utility-class explosion → CSS parser malformed).
outcome: failed
date: 2026-05-19
fix_layer:
failure_keys: [fetch_list_selector_syntax_error, tailwind_arbitrary_value_class, posts_nonempty]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [arxiv-2601-bench, video-platform, tailwind, css-parser, modern-frontend]
requested_by: 운영자 (prior-art followup — arxiv-2601-bench 11 사이트 자동 등록 측정)
vocab_candidates:
  - candidate: tailwind_attr_selector_explosion
    confidence: high
    evidence:
      - "experiments/arxiv-2601-bench/bot_results.md §11 (Vimeo — attempt 1 row_selector 에 `md:col-[3/-3]`, `lg:gap-x-lohp-lg` 등 tailwind arbitrary value class 박혀 `SelectorSyntaxError: Malformed attribute selector at position 33`)"
      - experiments/arxiv-2601-bench/bot_results.md §11 (attempt 3 — 같은 class 들 `\\:` `\\[` 등 escape 시도 했으나 다른 이유로 실패)
    reasoning: "Vimeo (및 modern Tailwind frontend) = utility class 가 `md:col-[3/-3]`, `lg:flex-col` 같은 arbitrary value / responsive variant 포함. CSS selector parser (bs4 의 soupsieve) 가 `[`, `]`, `:`, `/` 를 attribute selector 문법으로 해석 → malformed. config_writer 가 *raw class 박는 습관* (한국 사이트 의 utility class 짧음, prompt training distribution 안에 tailwind explosion 없음) → 영문/현대 사이트에서 깨짐. prompt 룰 추가: `class 가 [ : / 포함하면 그 class 박지 말고 tag + data-* + 짧은 stable class 1-2개로 selector 구성`. 또는 stable wrapper class (`card-set-grid`) 하나만 박고 자식은 tag (`> li`) 만. 본 case = 단일 사이트 evidence 지만 vocab vs prompt 룰 결정 명확 — prompt 룰 1개 추가가 정답."
    analysis_date: 2026-05-19
    deferred: true
---

## 무엇이 일어났나

`/watch https://vimeo.com/` (arxiv-2601-bench #11). 3 attempts 모두 실패.

attempts:
- attempt 1: `playwright_html` + row_selector 에 30+ tailwind utility class (`ul.card-set-grid.grid.w-full.col-[2/-2].grid-cols-1.gap-x-lohp-lg.gap-y-5.md:col-[3/-3].md:gap-x-5.md:gap-y-[3.718rem].md:px-0.md:grid-cols-2.lg:grid-cols-3.lg:gap-x-lohp-lg > li`) → `fetch_list: 실행 실패: SelectorSyntaxError: Malformed attribute selector at position 33`
- attempt 2: `httpx_html` + `ul.card-set-grid > li` (narrow) → posts_nonempty 0건
- attempt 3: `httpx_html` + `ul.<수십개 escape 된 class>` (`\:`, `\[`, `\/` 박음) → 다른 fail 또는 truncate

## 왜

Vimeo 홈페이지 = Tailwind utility-first frontend. row 컨테이너 class 가:
- `col-[2/-2]` = CSS Grid arbitrary value
- `md:gap-x-lohp-lg` = breakpoint + project-local variable
- `md:col-[3/-3]` = responsive + arbitrary value

bs4 의 `soupsieve` CSS parser 가 `[`, `:`, `/` 를 *attribute selector 문법* 으로 해석. raw class
박으면 `Malformed`. escape (`\:`, `\[`) 박아도 CSS 명세상 일부만 valid + 정적 응답에 *클라이언트
hydration 후에만* 박히는 class 면 매칭 0.

attempt 2 `card-set-grid > li` = stable class 만 박는 정공법인데 정적 응답에 이미 grid 가 빈
shell → 0건. 즉 *attempt 2 가 정답 selector + playwright_html 이 정답 strategy* 였으나 prompt
가 그 조합을 박지 않음.

## 픽스

**현재 없음**. 단일 prompt 룰 추가로 회복 가능성 높음.

### prompt 개선 (Action C 의 핵심)

`config_writer.system.txt` 에 추가:

> row_selector 의 class 가 `[`, `:`, `/` 포함하면 (tailwind arbitrary value / responsive variant)
> CSS parser 가 malformed 처리. 그 class 빼고 *stable, 짧은* class (예: `card-set-grid`, `vrow`,
> `feed-item`) 1-2개 + tag selector (`> li`) 만 사용. 정적 응답 시 빈 shell 면 strategy =
> `playwright_html` + `wait_selector` 로 hydration 대기.

위 룰 박으면 Vimeo 회복 시나리오:
- `playwright_html` + `ul.card-set-grid > li` (stable class 만) + `wait_selector: "ul.card-set-grid li"`

### 손-config (대체)

위 selector 직접 박으면 작동 가능. 단 prompt 개선이 일반화 가치 높음.

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§11.

## preflight 결과 (2026-05-19, SKILL.md §0b 적용)

[[infra_handconfig_preflight_reuse_probe_2026-05-19]] 의 (b) 검사. `register.py "https://vimeo.com/"` 결과:
- attempt 1 (httpx_html): FAIL — `posts_nonempty: 0건` (정적 fetch 의 빈 shell)
- attempt 2: FAIL — 동일
- attempt 3: FAIL — `posts_nonempty: 0건` (row_selector 'item')

prompt §8a 룰 (tailwind 가드) *적용 후* selector 길이 자체는 짧아짐 (`ul.flex.gap-5 > li.rounded-video` 같은 형태) — malformed 사라짐. 단 *정적 응답이 빈 shell* 이라 strategy=playwright_html + wait_selector 시도 안 했음. probe digest 의 `feed_candidates=2건` (RSS) 후보 활용 안 함.

→ **§2 진입 대상**. 다음 batch 손-config — 옵션:
1. RSS feed URL 확인 후 `httpx_json` (또는 RSS adapter) 시도
2. `playwright_html` + `wait_selector: ul.card-set-grid li` (전 turn case body 의 권장)
3. recognizer 신규 — `vimeo.com/<user>` 패턴 (사용자별 feed)

prompt §8a 룰만으로 회복 X = "stable wrapper class + tag" 권고가 *strategy 변경* 까지 trigger 안 함. 다음 prompt 강화 후보 = "정적 응답에 row anchor 없으면 자동 playwright_html + wait_selector".

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only. Action C 의 tailwind 가드 룰 trigger.
2. **이전 케이스 있나?** — 한국 사이트 중 tailwind explosion fail 없음 (학교 JSP / 게임 SSR 사이트
   대다수 가 jQuery-era class). 본 case = 분포 외 첫 evidence.
3. **재발 방지?** — prompt 룰 1줄 추가로 회복 가능. 다른 modern frontend (Notion / Linear / 새 SaaS
   사이트) 등록 시도 시 영향.
4. **자가 의심?** — bench 1회. Tailwind class 자체는 안정 (config 의 책임).
5. **회귀 검증?** — fix 미배포.
