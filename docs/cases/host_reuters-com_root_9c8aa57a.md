---
slug: host_reuters-com_root_9c8aa57a
url: https://www.reuters.com/
status: 🚫 거부 (Reuters root 도메인 마케팅 랜딩 + SPA shell — board 아님. 카테고리/섹션 URL 권장) — root_marketing_homepage 게이트 (C+F+A)
outcome: rejected_with_policy
date: 2026-05-19
fix_layer: C
failure_keys: [fetch_list_401, fingerprint_hide_required, posts_nonempty, matches_probe_first_article, count_ballpark, root_marketing_homepage]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/register.py, scripts/probe.py, prompts/config_writer.system.txt, bot/fail_taxonomy.py]
tags: [reuters, root-marketing-homepage, spa-shell, akamai, body-empty-likely, gate-reject, policy-reject, infra-root-gate, arxiv-2601-bench]
requested_by: poi23619
vocab_candidates:
  - candidate: fingerprint_hide_required
    confidence: high
    evidence:
      - experiments/arxiv-2601-bench/bot_results.md §8 (Reuters — httpx 401 모두, playwright 0건)
      - "[[arca-live_trickcal_6703bf64]] vocab_candidates (같은 후보, 다른 사이트 — Cloudflare)"
    reasoning: "Reuters 는 Akamai bot manager 가 TLS/UA fingerprint 검증. httpx 100% 401 (UA 변경 무관). playwright (naive) 도 페이지 접근은 되나 *body 가 challenge page* 인 듯 → row_selector 가 본문 카드 못 잡아 0건. [[arca-live_trickcal_6703bf64]] (Cloudflare) 와 *방어 인프라는 다르지만 (Akamai vs Cloudflare) 표면 증상 동일* — TLS fingerprint impersonation 또는 playwright-stealth 가 필요. 본 case = 같은 vocab 후보의 두 번째 high evidence. ADR 0003 임계 `high≥1 + total≥3` 의 trigger 후보 (현재 high=2). closed vocab `list.stealth: \"minimal\"|\"full\"|null` 또는 별 strategy `playwright_stealth` 어휘 추가 평가."
    analysis_date: 2026-05-19
    deferred: false
---

## 갱신 (2026-05-19 turn 2) — root_marketing_homepage 영구 게이트로 거부

기존 §"왜" / §"픽스" 의 fingerprint-hide 진단은 *board 진입 가정* 분석 (= Akamai bot manager 우회). 본 turn 에서 **Reuters root = SPA shell + 뉴스 hub = board 정의 X** 를 인정하고 [[infra_root_marketing_homepage_gate_2026-05-19]] 영구 게이트 박음:

- probe `list_candidates.root_marketing_homepage` 휴리스틱 매칭. Reuters 신호: `marketing_hits=3 total_same_host=8 body_empty_likely=True` (SPA shell — 정적 HTML 본문 비어있음). top selectors: `nav-dropdown-module__subsections`, `VideoShortsCarouselContainer`, `nav-dropdown-module__sections-group`
- `.REJECTED.json` 마커 + `learn=False`
- 사용자에 안내: `카테고리/섹션 URL 시도 권장 — 예: https://www.reuters.com/world/` (probe first_article=`/world/<...>-2026-05-18/` → `/world/` segment)

기존 vocab_candidate `fingerprint_hide_required` (high=2, [[arca-live_trickcal_6703bf64]] Cloudflare 와 누적) 는 *root 우회 후 카테고리 URL 시도 시* 여전히 활성. ADR 0003 임계 도달 가능성 남음 (현재 high=2, +1 추가 시 trigger). root 게이트는 *그 vocab 후보를 보호* — root 등록 시도가 fingerprint 우회 비용 0 으로 끝남.

## 무엇이 일어났나

`/watch https://www.reuters.com/` (arxiv-2601-bench #8). 3 attempts 모두 실패.

attempts:
- attempt 1: `httpx_html` + `main [data-testid="StoryCard"]` → `fetch_list` 실행 실패 `HTTPStatusError: Client error '401 HTTP Forbidden'`
- attempt 2: 동일 (httpx_html) — 같은 401
- attempt 3: `playwright_html` + 같은 selector → `posts_nonempty` 0건

## 왜

Reuters = Akamai bot manager 인프라. httpx 의 TLS handshake fingerprint (JA3/JA4) 가 진짜
Chrome 과 다름 → 즉시 401. UA / Accept 헤더 변경해도 통과 X (TLS 단계가 먼저).

playwright (Chromium headless) = 페이지 *접근* 은 200 OK 인 듯 (fetch_list 자체는 실행됨)
이나 응답 body 가 *Akamai challenge page* (또는 SPA 의 빈 shell + `__NEXT_DATA__` 안에 글 있음)
→ row_selector `[data-testid="StoryCard"]` 정적 매칭 0건.

## 픽스

**현재 없음**. 두 갈래:

### 갈래 1: prompt 개선 만으론 부족

config_writer 가 어떤 prompt 받아도 closed vocab 에 stealth 어휘 없음 → 회복 경로 X. vocab 확장
필요.

### 갈래 2: vocab 확장 (`fingerprint_hide_required` 임계 도달 시)

ADR 0003 `/vocabulary-extension` SKILL 호출. 후보 어휘:

| 후보 | trade-off |
|---|---|
| `list.stealth: "minimal"\|"full"\|null` | `playwright_html` strategy 의 sub-option. minimal = 3옵션 (webdriver hide + AutomationControlled disable + 정상 UA). full = playwright-stealth 패키지. closed vocab 변경 최소 |
| 새 strategy `playwright_stealth` | strategy enum 1개 추가. 명확하나 generator 코드 곳곳 분기 추가 비용 |
| Akamai-specific adapter (수동) | 단일 사이트 해결, 일반화 X |

minimal stealth 가 prior-art-bench 의 arca 에서 70% 통과 했음 → reuters 도 가능성 있음 (별
bench 측정 가치).

### 갈래 3: 정책 거부

`docs/크롤링 지침.md` = TLS impersonation / stealth 강도 높임 = 우회. 본 프로젝트 정책상 *허용 안
함* 가능성 — vocab-ext SKILL 호출 시 reviewer 가 정책 측면 판단 필수.

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§8.

## preflight 결과 (2026-05-19, SKILL.md §0b 적용)

[[infra_handconfig_preflight_reuse_probe_2026-05-19]] 의 (b) 검사. `register.py "https://www.reuters.com/"` 결과:

```
[register] 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='분류 보류').
차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음. 등록 거부.
```

verdict = BLOCKED. **register.py 자동 거부** — 정책 (`docs/크롤링 지침.md` = 우회 X) 가 본 case 의 결정. *prompt §8a 룰 영향 없음* — Akamai bot manager 차단이 1차, prompt 는 row_selector 단계 의 룰.

→ **§2 진입 X — 정책 거부 종료**. fingerprint_hide_required vocab 임계 도달 시 (arca + reuters = high=2, 1건 더 필요) 별 작업으로 vocab-ext SKILL 호출 평가. 단 정책 reviewer 가 *우회 안 함* 결정하면 본 case 영구 REJECTED.

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only. fingerprint_hide_required vocab-ext trigger 의 두 번째 high
   evidence. arca + reuters 합쳐 임계 도달 가속.
2. **이전 케이스 있나?** — [[arca-live_trickcal_6703bf64]] (Cloudflare), [[host_techethics-ieee_about_bdcbf970]]
   (JA3 차단, single about page) — 후자는 정책 거부.
3. **재발 방지?** — vocab 확장 시 register-rate 회복 가능. 단 정책 측면 판단 선행 필요.
4. **자가 의심?** — bench 1회. Akamai 응답이 시간대/IP 변동 가능.
5. **회귀 검증?** — fix 미배포.
