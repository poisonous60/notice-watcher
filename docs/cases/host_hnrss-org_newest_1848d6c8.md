---
slug: host_hnrss-org_newest_1848d6c8
url: https://hnrss.org/newest
status: ✅ probe feed content-sniff 추가 (path 모양 무관 직접-피드 검출)
outcome: improved
date: 2026-05-20
fix_layer: C
failure_keys: [board_shape, feed_url_shape_miss]
config_strategy: none
engine_files_touched: [probe/discover.py]
tags: [probe, heuristic, rss, feed-detection, board_shape, batch-2026-05-20-b]
requested_by: catalog 2026-05-20-b
---

## 무엇이 일어났나

batch 2026-05-20-b 의 직접-RSS-피드 URL 여럿이 board_shape 거부:

> ❌ 등록 거부 — 게시판 형식 아님. [신호: ... feed=0 ...]

- `hnrss.org/newest` (피드 토큰 없는 path)
- `www.phoronix.com/rss.php` (`rss` 뒤 `.php`)
- `www.gamespot.com/feeds/news/` (`/feeds/` 뒤 path 계속; + robots Disallow:/ UA 차단 의심)

dev 박스 직접 fetch 결과 셋 다 **200 + valid `<rss>` XML** (browser UA). 즉 정상 피드인데
probe 가 피드로 인식 못 함.

## 진단 (분기 2c — 신호는 page_html 에 있는데 휴리스틱화 안 됨)

`probe/discover.py:discover_feeds` 의 피드 검출 = (1) `_looks_like_feed_url` (URL **path 모양**
휴리스틱) + (2) HTML `<link rel=alternate>` + (3) host 루트 well-known path. 직접-피드 URL 의
path 가 `/rss /feed .xml` 모양이 아니면 (1) 실패, 본문이 XML 이라 (2) 도 없음, (3) 은 host
루트만 봐서 board-별 피드 path 못 잡음 → feed_candidates 빈 채 board_shape false-reject.

핵심: **page_html 자체가 RSS XML 인데** 본문 content 를 안 봤음.

## 트랙 B (영구)

`_body_is_feed(text)` 순수 함수 추가 — lstrip 후 root 태그 (`<?xml`/`<rss`/`<feed`/`<rdf`) 로
피드 검출. `discover_feeds` 에서 `_looks_like_feed_url` 미스 시 `_body_is_feed(page_html)` 폴백 →
source `input-url-feed-content` candidate 박음. path 모양 무관 → 임의 직접-피드 URL 자동 통과.

fixture `tests/probe_heuristics/test_body_is_feed.py` 10 cases (rss/atom/rdf/공백/HTML-아님/
sitemap-아님 + url-shape-miss 회귀 가드).

## 트랙 A (즉시)

배포 후 hnrss/phoronix 재등록 → feed_candidates 채워져 board_shape 통과 → httpx_html RSS config
생성. gamespot 은 robots Disallow:/ + UA 차단 가능성 별개 (probe 가 본문 못 받으면 sniff 도 무력 —
content 받으면 통과).

## 회귀 검증

probe_smoke stage 5 488 cases 0 FAIL (신규 test 포함). `_body_is_feed` HTML/빈/sitemap = False
확인 (false-positive 차단).
