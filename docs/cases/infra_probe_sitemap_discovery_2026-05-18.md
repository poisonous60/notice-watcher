---
slug: infra_probe_sitemap_discovery_2026-05-18
url: (인프라 case — 특정 사이트 X. 트리거 = prior-art 조사 followup-plan Action #1)
status: 🏗 인프라 (probe Phase 6 의 sitemap.xml 디스커버리 — docstring 의도 미구현분 채움)
outcome: improved
date: 2026-05-18
fix_layer: C
failure_keys: [posts_nonempty, user_url_not_board_page]
config_strategy:
adapters_changed:
engine_files_touched: [probe/discover.py, probe/_contract.py, scripts/probe.py, engine/digest.py, prompts/config_writer.system.txt]
tags: [probe-phase6, sitemap-xml, robots-txt, url-discovery, board-candidate-recovery, do-not-redo-with-retry-loop]
requested_by: 운영자 (prior-art 조사 §6 #1 followup-plan)
---

## 트리거

`docs/2026-05-18-prior-art-조사.md` §3a (Firecrawl `/map` 분석) → `docs/2026-05-18-prior-art-followup-plan.md` Action #1.

가설: 사용자가 *board 아닌 URL* (도메인 root, 홈, 카테고리 메뉴) 던지면 register 가 `posts_nonempty` 로 실패 — `/map` 비슷한 메커니즘으로 후보 board URL 회복하면 자동 등록 회복 가능. bench (조사 §3a):
- `cse.skku.edu/` → 15 entry (`/cse/notice.do` 포함)
- `gamemeca.com` → 11 entry (`/news.php` 포함)
- `cafe.naver.com/gutterlife` → 1 entry (iframe/login — 한계)

## ❌ 잘못 간 길 (commit `ea26370` → revert `451b582`, commit `160936b` → revert `9637559`)

**시도 1 — Firecrawl hosted API** (`ea26370`):
- `engine/url_discovery.py` 신규 — Firecrawl `/map` POST httpx 래퍼
- `scripts/register.py` `GenerationError` catch → fallback `_gen` 1회 더 호출
- FIRECRAWL_API_KEY env 의존, free 500 credit/월
- **문제**: 호스티드 API 의존, 키 관리, credit 부담 (rate_limit 의도 안 가르킴)

**시도 2 — 직접 구현, engine/ 위치** (`160936b`):
- Firecrawl OSS clone + codex 리뷰 (DIRECT-IMPL-OK) — self-host Firecrawl 도 sitemap.xml + crawl 만 사용 (Fire-engine/queryIndex hosted only) → 직접 구현 가능
- `engine/url_discovery.py` 직접 구현 (sitemap + robots + a[href])
- `scripts/register.py` `_try_url_discovery_fallback` — 같은 retry loop 구조
- **문제 (운영자 지적)**: "이거 retry 다 실패하기 전에 주면 안 돼? 지금 retry 루프를 하나 더 만든거야? 그럼 안되는데"
  - LLM 호출 4 + 4 = 8회 (2배). 토큰 폭증.
  - "engine/ 으로 뺀 이유 없음 — probe 의 결과물이 되어야"

## ✅ 옳은 길 (commit `30b9532`, 현재)

자리 = **`probe/discover.py` Phase 6** — docstring 에 이미 "RSS/Atom + robots.txt + sitemap 디스커버리" 명시 (단 sitemap 부분 미구현). retry 추가 X — digest 가 i==1 부터 사용.

구현:
- `probe/discover.py`:
  - `read_robots()` 확장 — `Sitemap:` 라인 추출 → `info["sitemaps"]`
  - `fetch_sitemaps()` 신규 — robots.sitemaps + 표준 경로 폴백 (`/sitemap.xml`, `/sitemap_index.xml`, `/sitemap.xml.gz`) → 재귀 sitemapindex + gzip + namespace 유무 둘 다 + byte cap (10MB) + gzip bomb 방어 (`zlib MAX_WBITS|16`) + same-host filter + board-like 점수 정렬 (cap 100)
- `probe/_contract.py` — robots.json 에 `sitemaps` 필드, sitemap.json contract 신규
- `scripts/probe.py` Phase 6 — read_robots 후 `fetch_sitemaps` sequential 호출 (robots 결과 의존)
- `engine/digest.py` — sitemap.json → digest 의 `sitemap_candidates` 키
- `prompts/config_writer.system.txt` — `sitemap_candidates` 어휘 (사용자 board 아닌 URL 던지고 list_html 못 잡으면 후보 시도)
- `tests/probe_discovery/test_fetch_sitemaps.py` — 13 케이스 (httpx MockTransport)
- `tests/probe_heuristics/test_contract.py` — OUTPUT_SCHEMA 완전성 6 → 7

## 비용 / 폴링 영향

| 단계 | 비용 |
|---|---|
| probe 실행 | robots + sitemap fetch ~1~3s 추가 |
| generate | LLM 호출 4회 그대로 (이전 시도 8회 → 회복) |
| 폴링 | 0 (probe 시점만) |
| credit | 0 (외부 API X, httpx + bs4) |

## 같은 일 다시 하지 마라 — 함정 정리

1. **engine/ 으로 빼지 마라**. URL 후보 디스커버리 = probe 의 일. `probe/discover.py` Phase 6 에 합쳐야 자연 (docstring 의도).
2. **retry 루프 추가하지 마라**. digest 에 *항상* 박혀 i==1 부터 LLM 가 참조. fallback 같은 구조는 LLM 토큰 2배 + 사용자 wait 2배.
3. **외부 API 의존 (Firecrawl hosted) 하지 마라**. SELF_HOST.md 명시: Fire-engine / queryIndex = hosted only. 즉 self-host 도 sitemap.xml + crawl 만. = 직접 구현으로 동등.
4. **`bot/url_gate.py` 손대지 마라**. URL gate = 정책/SSRF 자리. discovery 와 책임 분리.
5. **bench 효과 = 일부 사이트만**. naver_cafe 같은 iframe/login-walled = robots/sitemap 도움 X (1 entry). robots/sitemap 없는 사이트도 동일. *없는 것보단 낫다* 수준.

## 회귀 검증

- `tests/probe_discovery/test_fetch_sitemaps.py` — 13 PASS
- `tests/probe_heuristics/test_contract.py` — OUTPUT_SCHEMA 7 종 완전성
- `scripts/probe_smoke.py --stage 3 --stage 5` — 358 PASS (37 config validate + 320 heuristic units)

## 관련

- `docs/2026-05-18-prior-art-조사.md` §3a — bench 결과 (skku 15, gamemeca 11, naver_cafe 1)
- `docs/2026-05-18-prior-art-followup-plan.md` Action #1 — plan v2 (codex 14 findings 반영)
- commit `ea26370` (revert) — Firecrawl hosted API 시도
- commit `160936b` (revert) — engine/ 직접 구현 시도
- commit `30b9532` — probe-native (현재)
