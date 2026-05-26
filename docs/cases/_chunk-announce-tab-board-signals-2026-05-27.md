---
slug: _chunk-announce-tab-board-signals-2026-05-27
url: -
status: "✅ improved — `_heterogeneous_hub_check` announcement-tab escape 에 API-identity·dense-under-board·click-resolved 3종 추가"
outcome: improved
date: 2026-05-27
fix_layer: F
failure_keys: [heterogeneous_hub_check, announcement_tab_escape, query_placeholder_article_shape, article_api_url_id_match, dense_cluster_under_board]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py, tests/test_hub_gate_rss_escape.py, scripts/register_batch.py, scripts/remote.py]
tags: [batch-2026-05-24-games-jp, false-reject, heterogeneous-hub-gate, announcement-tab, cross-site-generalization]
---

## 신호

`_heterogeneous_hub_check` (gen_fail post-mortem 게이트) 가 *announcement-tab URL 인데 정적 pagination 만 없음* 인 사이트를 false-reject 한 cross-site 패턴.

같은 2026-05-24-games-jp batch 의 같은 거부 메시지(`clean article cluster 0종`) 2건 — §0c-0 1번 (agentic 자리 박기, cross-site generalization) 적용.

| trigger slug | URL | 정적 신호 | OLD 결과 |
|---|---|---|---|
| host_granbluefantasy_news_8cb478ee | https://granbluefantasy.jp/news/ | cluster cc=7 `/ja/news/` (nav 로 분류) + reprobe article API `rcms-api/news/details/9704` `url_id_match=True` + click resolved `granbluefantasy.com/ja/news/9704/` (cross-host article URL) | REJECT — clean article cluster 0종 |
| host_nexon-co-jp_news_0d39ba12 | https://www.nexon.co.jp/news/ | cluster cc=755 `/news/detail?id={n}-23a5e007` (placeholder 가 *query* 에 — path 마지막 segment 는 `detail`) + verdict `정적 응답이 빈 shell — JS 카드 그림` (SPA) | REJECT — clean article cluster 0종 |

기존 atlus / fate-go (2026-05-26 atlus case) 패치는 *정적 pagination* + *underscore 슬러그 article-shape* 만 해결. announcement-tab URL 이면서 다음 3종 신호 중 하나라도 있는 사이트는 여전히 false-reject:

1. preflight reprobe 의 본문 JSON API 후보가 글 ID 별로 발급되는 endpoint (`url_id_match=True`) — granblue 의 `rcms-api/news/details/9704`
2. 같은 호스트 cluster 가 board_path 아래로 가는 high-density (cc≥20) — nexon 의 `/news/detail` (cc=755) under `/news/`
3. Phase 9b click 이 진짜 article URL (depth≥2 + 숫자/slug 마지막 segment) 로 resolve — granblue 의 `/9704/`

## fix layer 매핑

§6 6 자리 위에서부터 — (E)/(D)/(C) 자리 없음, **(F) 게이트 escape 룰 확장**.

(C) 자리는 이미 충분: probe digest 에 `article_sample.api_candidates`(이미 reprobe 가 채움)·`article_sample.clicked_resolved_url`(이미 click 이 채움)·`list_candidates.html_repeating_patterns.child_count` 모두 존재. **게이트가 안 읽었던 게 문제**. 새 휴리스틱 추가 X — 기존 신호 활용만 늘림.

### (F) `scripts/register.py:_heterogeneous_hub_check`

announcement-tab path (`_ANNOUNCEMENT_TAB_RE` 매칭) 일 때 escape 조건 확장 — 기존 `pagination_hints ≥1` 만 → 다음 *어느 하나라도* 통과:

| 신호 | 의미 | 트리거 사이트 |
|---|---|---|
| (기존) `lc.pagination_hints ≥1` | 정적 pagination link | atlus·fate-go |
| (신규) `article_sample.api_candidates` 중 `url_id_match=True` 1+ | 서버가 글 ID 별 본문 endpoint 발급 = 실제 article inventory | granblue |
| (신규) 같은 호스트 cluster `cc≥20` + path 가 board_path 아래 | dense article inventory under announcement tab | nexon |
| (신규) `clicked_resolved_url` 이 진짜 article URL (depth≥2 + 숫자/mixed-alnum/긴 slug 마지막 segment) | Phase 9b click 이 article 까지 도달 = 실제 board | granblue·umamusume·다수 SPA |

추가로 `is_article_shape` 도 *query string placeholder* 인식:

- 기존: `last segment` 에 `{...}` 또는 8+ char slug/id 만 article 로 인정
- 신규: `cc≥20` + `under_board=True` + `href_pattern_guess` 의 query 에 `{...}` → article 로 인정 (nexon 의 `/news/detail?id={n}-...`)
- 이 둘은 *함께* 작용 — escape 가 일찍 None 반환하면 cluster 분류까지 안 가지만, escape 미해당 + query placeholder dense cluster 인 사이트는 cluster 분류 단계서 article 로 잡혀 통과.

### (보조) `scripts/register_batch.py:--failed` 인자 split (gen|blocked|all)

batch retry 시 capability_blocked(rc=5) 와 gen_fail(rc=1) 을 같이 돌리지 못하던 게 사용자 unblock. `--failed=gen` (rc∈{1,-1,-2,-3,-99}) / `--failed=blocked` (rc=5) / `--failed` bare = all (기존 동작). `scripts/remote.py` 도 같은 인자 패스스루.

이 case 의 retry 흐름이 `--failed=gen` 사용 — capability_blocked 재시도와 분리해서 진행.

## 회귀 검증

```
python -m pytest tests/test_hub_gate_rss_escape.py -x -q
8 passed in 0.65s

python -m pytest tests/llm/test_register_auto_mode.py -x -q
8 passed in 0.57s

python scripts/probe_smoke.py --stage 3 --stage 5
=== summary === PASS 1537 FAIL 0 WARN 1 SKIP 0
```

실제 artifact replay (§5 step 1b):

```python
# granblue probe artifact 로 게이트 직접 호출 — NEW: None (escape 성공)
# nexon probe artifact 로 게이트 직접 호출 — NEW: None (escape 성공)
```

기존 거부 케이스 unaffected — wheresyoured.at root (validated RSS 없을 때 reject 유지), root URL (`/`) 은 announce 체크 안 들어감.

## 일반화 후보 / 검토

매칭 0건 — 본 case 자체가 *3 신호 generalization* 임. 다음 같은 패턴 사이트는 자동 통과 예상:

- 일본 게임 회사 announcement page (umamusume·fate-go 외 다수) 가 SPA + body API + click-only 패턴
- 한국 일본 CMS news 페이지 (rcms·CMS_HOME 류) 가 announcement-tab + body JSON API 패턴
- 모든 SPA news index — Phase 9b click 으로 article URL 잡히면 자동 통과

향후 같은 패턴 2+ trigger 시 본 case 의 `## 후속` 섹션에 1줄 명시.

## 배포 메모

- commit + push (pre-push hook = probe_smoke 통과)
- N100 `git pull` (register 코드만 변경, bot import 캐시 영향 X → service restart 불필요)
- 4 hand-config 동시 배포: hoyoverse·capcom-games·drecom·shadowverse (prior session untracked, 이번 batch 재시도 안 도는 사이트 즉시 등록 효과)
- `python scripts/remote.py batch-register --catalog=2026-05-24-games-jp --failed=gen` retry — gate fix 효과로 granblue/nexon (rc=3 자동 REJECTED 였지만 untried 자동 enqueue X — 별도 처리 필요)

## granblue/nexon 의 retry 경로

이 둘은 이미 N100 에서 `rejected` (rc=3) 라 `--failed=gen` 대상 아님 (failed status 만 retry). **사용자 명시 fix 요청 = `--url` 으로 직접 재시도**:

```bash
python scripts/remote.py batch-register \
  --url https://granbluefantasy.jp/news/ \
  --url https://www.nexon.co.jp/news/
```

(rejected 마커는 `register.py` 가 새 게이트 통과 시 cleanup.)
