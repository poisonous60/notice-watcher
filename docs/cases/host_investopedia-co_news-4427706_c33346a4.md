---
slug: host_investopedia-co_news-4427706_c33346a4
url: https://www.investopedia.com/news-4427706
status: 🚫 거부 (게시판 형식 아닌 것으로 판정 — candidates_zero / list_url_none).
outcome: rejected
date: 2026-05-19
fix_layer:
failure_keys: [candidates_zero, list_url_none, posts_nonempty, hub_url_not_board]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [arxiv-2601-bench, news-hub, url-discovery, sitemap-map-candidate]
requested_by: 운영자 (prior-art followup — arxiv-2601-bench 11 사이트 자동 등록 측정)
vocab_candidates:
  - candidate: list_url_recovery_via_map
    confidence: low
    evidence:
      - "experiments/arxiv-2601-bench/bot_results.md §3 (Investopedia/news-4427706 — 거부 사유: 반복 글 링크/목록 API/피드 안 보임)"
    reasoning: "`/news-4427706` = Investopedia 의 News 섹션 hub. 정적 GET 응답에 카드 anchor 부족 (SPA hydration 후 박힘). board page 자체는 *존재* 하나 정적 응답이 빈 shell. probe 의 candidates_zero 거부 정상 — 단 *Firecrawl `/map` 또는 sitemap 디스커버리 후 list_url 변경 시* 회복 가능성. prior-art 조사 §3a (Firecrawl `/map` 통합) 의 첫 evidence. confidence=low — 단일 사이트, sitemap 통합 자체가 별 작업."
    analysis_date: 2026-05-19
    deferred: true
---

## 무엇이 일어났나

`/watch https://www.investopedia.com/news-4427706` (arxiv-2601-bench #3). 봇 응답:

```
⚠️ 등록 거부 — host_investopedia-co_news-4427706_c33346a4
이 URL 은 게시판 형식이 아닌 것 같아요(반복되는 글 링크/목록 API/피드가 안 보입니다).
게시판/공지 목록 페이지 URL 을 주세요.
```

probe 결과 candidates_zero — repeating row 패턴 / JSON API / RSS 어느 것도 잡히지 X.

## 왜

`/news-4427706` = Investopedia 의 News 섹션 hub. URL 의 `-4427706` = 카테고리 ID (taxonomy
term ID). 페이지 자체는:
- 정적 GET 응답 = 헤더 + 빈 shell + 클라이언트 hydration script
- 카드 anchor (`<a href="/news/<slug>">`) = JS 가 박음
- 봇 probe 의 정적 fetch 단계가 anchor 못 찾아 candidates_zero

봇 가드 = `list_url_none` + `candidates_zero` → "게시판 아님" 으로 거부. **이 거부는 정상 동작** —
정적 fetch 만으론 list 못 잡는 사이트를 자동 distinguish 못 함 (board 인지 not-a-board 인지).

단 실제 *News 섹션 hub 는 list 자체* — Firecrawl `/map` 또는 sitemap.xml 발견 시 board 인 게
드러남. probe Phase 6 (이미 sitemap discovery 추가됨, [[infra_probe_sitemap_discovery_2026-05-18]])
가 Investopedia sitemap 발견 시 후속 회복 가능성.

## 픽스

**현재 없음**. 경로 2가지:

### 경로 1: probe Phase 6 sitemap discovery 가 Investopedia 잡았는지 확인

[[infra_probe_sitemap_discovery_2026-05-18]] (commit 30b9532) 후 새 probe 돌리면 `sitemap.xml`
또는 robots.txt `Sitemap:` 라인 발견 가능. 가능성:
- Investopedia 가 sitemap 에 `/news-*` hub URL 박았으면 → score 매겨 list candidate 등극
- sitemap 이 article URL 만 박혔으면 → 회복 불가, 결국 정책 거부 정당

### 경로 2: Firecrawl `/map` 통합 (prior-art §3a, 별 작업)

정적 sitemap 없는 사이트도 `/map` 으로 internal link 발견. Investopedia 는 sitemap 있을 가능성
크니 경로 1 우선.

## 영향

- 정책 거부 = 사용자 영향 X (정상 동작)
- 단 *진짜 board 인데 거부* 한 first case — 경로 1 후속 시 회복 가능성 evidence
- 같은 패턴 (`/news-<id>` hub) 다른 사이트들 (CNN International, BBC sport, Reuters 일부 섹션
  hub URL 등) 도 같은 거부 경로 가능

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§3.

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only. [[infra_probe_sitemap_discovery_2026-05-18]] 의 후속 검증 trigger.
2. **이전 케이스 있나?** — [[host_omate-kr_news_3ff5e0f9]] (사용자가 articleView URL 줌 → articleList 변환) 와
   *URL discovery 필요* 측면 같은 카테고리. 단 omate 는 변환 룰 수동 박았고, 본 case 는 sitemap 자동.
3. **재발 방지?** — sitemap discovery 가 Investopedia 잡으면 자동, 못 잡으면 Firecrawl `/map` 통합 필요.
4. **자가 의심?** — bench 1회. 새 probe 돌려야 sitemap discovery 효과 확인.
5. **회귀 검증?** — fix 미배포 (sitemap discovery 는 별 commit, 본 case 가 검증 trigger).
