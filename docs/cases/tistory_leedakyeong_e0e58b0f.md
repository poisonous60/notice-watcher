---
slug: tistory_leedakyeong_e0e58b0f
url: https://leedakyeong.tistory.com/entry/Python-pandas-tutorial-drop-duplicates-in-pandas
status: ✅ 일반화 완료 (Tistory 플랫폼 — known-platform 인식기 + RSS adapter)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [posts_nonempty, static_vs_headless, feed_candidates, post_id_stable_shape]
config_strategy: handwritten
adapters_changed: [adapters/tistory.py, adapters/__init__.py]
engine_files_touched: [engine/recognizers/tistory.py, tests/recognizers/test_tistory.py]
tags: [self-improvement, recognizer, rss-adapter, tistory, platform-fast-path, static-vs-headless]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview https://leedakyeong.tistory.com/entry/Python-pandas-tutorial-drop-duplicates-in-pandas` → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] posts_nonempty: 0건` (3 attempts 다 0건). 동시에 `[warn] matches_probe_first_article` + `[warn] count_ballpark: 0건 (probe 후보 child_count≈77)`.

`diagnosis.json`:
- verdict: `캡처 헤더 주입 시 정적 가능` + note `정적 응답이 빈 shell — Playwright 응답이 정적보다 3.0배 크고 row-like 요소 (107 vs 101) 만 잡힘. JS 가 카드/목록 그리는 사이트 — strategy=playwright_html 필수`
- `feed_candidates=3건 (RSS/Atom)` ← **결정적 신호**

## 진단

§2a (목록 추출 실패 — SPA 빈 shell). Tistory 스킨이 사이트마다 달라 정적 row_selector 휴리스틱화 불가. 그런데 Tistory 는 *플랫폼 표준 RSS* (`<host>/rss`) 자동 발행 — naver_blog 와 동일한 패턴.

누적 cross-check (`cases_index.py query`):
- `posts_nonempty` count=12 → trigger
- `feed_candidates|rss|RSS` signal count=6 → trigger (naver-blog 2건 포함 = 같은 해결책 검증됨)
- `static_vs_headless` signal count=5 → trigger
- → **트랙 B 강제 진입**

## 픽스 (fix_layer: F — track A+B 동시 single PR)

### F-1. `adapters/tistory.py` — TistoryRssAdapter (신규)

`naver_blog.py:NaverBlogRssAdapter` 와 동형. 차이:
- host = `<subdomain>.tistory.com` (kwargs 로 주입)
- RSS endpoint = `https://<host>/rss`
- post_id = RSS `<guid>` 의 numeric ID (`https://<host>/271` → `271`) — `<link>` 의 entry-slug 는 64자 초과 가능 (URL-encoded 한글 슬러그 — 1글자=9~15자) → `_STABLE_ID_RE` (`max_len=64`) 위배 (실제 검증 fail 한 항목)
- 본문 = RSS `<description>` 에 HTML inline → fetch_list 가 채움 (`fetch_article` 도 그대로 반환). 비어있는 경우만 글페이지 fallback (selector chain: `div.tt_article_useless_p_margin.contents_style`, `div.area-view`, `div.entry-content` …)

### F-2. `engine/recognizers/tistory.py` — Tistory 인식기 (신규)

URL 폼 5종 (`/entry/<slug>`, `/<num>`, `/category/<cat>`, `/tag/<tag>`, root) 모두 매칭. builder 가 `host=<sub>.tistory.com`, `_slug_board=<sub>` 로 config 생성. Reserved subdomain (`www`, `m`, `blog`) None 반환 → article_page_reject 가 먼저 `www.tistory.com/` 잡음.

### F-3. `adapters/__init__.py` — TistoryRssAdapter export

### F-4. `tests/recognizers/test_tistory.py` — 인식기 10 case unit fixture

entry-slug / 숫자 / category / tag / root URL 매칭 + www/m subdomain reject + custom domain (`blog.example.com`) unmatched + `recognize()` integration.

## 영향

- **leedakyeong (이 case)** — slug 변경: `host_leedakyeong-tis_entry_e0e58b0f` → `tistory_leedakyeong_e0e58b0f` (hash 동일 — `canonical_url` 동일). 옛 `.FAILED.json` 수동 정리 + triage_queue 수동 prune.
- **미래 모든 tistory subdomain** — `/preview <url>` 즉시 recognizer 매칭 → probe/Gemini 0 비용 등록. 같은 패턴 FAILED 큐 1건 (`kevin0960`) + REJECTED markers (`benesiaxd`, `harley-hwan`) 다음 사용자 재시도 시 자동 회복.
- **slug schema migrate** — 새 인식기 추가 → 일부 옛 fallback slug (`host_<sub>-tisto_*`) 가 새 platform slug (`tistory_<sub>_*`) 로 변경. `scripts/migrate_slug_schema.py --dry-run` 결과: leedakyeong 충돌 (이번 case — 수동 해결됨). 다른 tistory 옛 slug 는 *.FAILED.json 만 있고 dev 박스에 *.json (성공 state) 없으므로 N100 배포 시 자연스럽게 새 slug 로 재등록.

## 회귀 검증

- `python tests/recognizers/test_tistory.py` → **10 PASS**
- `python tests/recognizers/test_article_page_reject.py` → **43 PASS** (기존 tistory root reject 도 그대로 — subdomain 별도 host)
- 라이브 스모크 (leedakyeong.tistory.com): `fetch_list` → 10 posts, post_id=stable numeric (`271`/`270`/...), body inline (`body_len=9982~48281`).
- `python scripts/register.py "<url>" --force`: ✅ 등록 완료, baseline 10건, learned_blacklist 매칭 패턴 자동 회수.

## 트랙 B 매칭 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ `tistory.py` 신규. host 패턴 한 줄.
- **2b (--article-url)**: ❌ probe 1차 신호 자체가 무용 — RSS 우회로 첫 글 식별 불요.
- **2c (probe heuristic)**: ❌ — `feed_candidates` 자체가 이미 휴리스틱 (probe/feed.py), prompt 에도 들어가지만 LLM 이 못 받아옴. Recognizer 가 더 결정적.
- **2d (probe artifact 수정)**: ❌.

트랙 A (사용자 향) + 트랙 B (미래 향) 동일 — 인식기 자체가 사용자 등록 즉시 작동 + 같은 패턴 미래 자동.

## 남은 정리

- N100 의 stale `output/poll_state/host_kevin0960-tisto_entry_0e610db5.REJECTED.json`, `host_benesiaxd-tisto_2_0ac1cf17.REJECTED.json`, `host_harley-hwan-git_2021-11-11-AttackLab_b6c964d8.REJECTED.json` — 다음 사용자 재시도 시 새 slug 로 재등록 (REJECTED marker 는 옛 slug, 새 slug 와 무관). 또는 사용자가 다시 `/preview` 한 번 누르면 새 slug 로 처리됨.
- harley-hwan.github.io 는 tistory X (github.io) — 인식기 미적용. 별도 case.
