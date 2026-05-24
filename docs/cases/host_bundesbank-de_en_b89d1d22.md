---
slug: host_bundesbank-de_en_b89d1d22
url: https://www.bundesbank.de/en/press
status: 🧩 수동 config — Bundesbank Latest RSS feed 로 baseline 10건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [article_body_len, wrong_first_article, nav_menu_as_list, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [bundesbank, press, rss, nav-candidates]
---

## 무엇이 일어났나

`/en/press` 는 press landing page 이고, 정적 HTML 안에는 press section 링크와 RSS 링크가 같이 있다.
probe 는 page-level navigation 안의 `Executive Board` 하위 인물 링크를 첫 글 및 반복 목록으로 잘못 잡았다.
그 결과 마지막 자동 config 는 `board=executive-board` 와
`/en/bundesbank/organisation/executive-board/...` URL 패턴으로 발산했고, 본문 검증에서 실패했다.

`last_feedback`:

- `[FAIL] article_body_len: post_id=837992 0자 (<100 — content selector 의심)`
- 실제 추출된 앞 글은 `Professor Joachim Nagel`, `Dr Sabine Mauderer`, `Burkhard Balz` 등 executive-board
  profile links 였다.

`diagnosis.json` verdict 는 `정적 HTTP로 충분` 이었지만, digest 의 반복 후보 top rows 는 nav/sidebar 쪽이었다.
같은 probe 산출물의 `feed_candidates.json` 은 공식 RSS 후보를 10건 찾았고, 그 중 `Latest` feed 는 fetch 검증된
`application/rss+xml` 응답이었다.

```json
{
  "source": "page-feed-link",
  "type": "application/rss+xml",
  "title": "Latest",
  "url": "https://www.bundesbank.de/service/rss/en/633306/feed.rss",
  "status": 200,
  "content_type": "application/xml"
}
```

## 픽스

`configs/host_bundesbank-de_en_b89d1d22.json` 을 RSS 기반 `httpx_html` config 로 작성했다.

- 목록: `https://www.bundesbank.de/service/rss/en/633306/feed.rss`, `row_selector: channel > item`
- `post_id`: RSS `guid` 또는 `link` 끝의 numeric id (`-(\d+)$`)
- `title/url/published_at/summary`: RSS `title/link/pubDate/description`
- 본문: 많은 항목이 PDF-only 또는 sparse press release page 라서 `body_empty_acceptable: true`

`board=executive-board` 는 자동 생성기의 오인 결과라 사용하지 않았다. 실제 submitted URL 은 press landing 이므로
config board 는 `press` 로 둔다.

## 회귀 검증

- recognizer preflight
  - `recognize("https://www.bundesbank.de/en/press")` -> `None`
- preflight 영향 변경 검사
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 3개: `964660`, `964718`, `997268`
  - 첫 글 `fetch_article()` 는 body length 0, config 에서 body empty 허용
- `python scripts/register.py --config configs/host_bundesbank-de_en_b89d1d22.json`
  - baseline 10건 등록
  - `output/poll_state/host_bundesbank-de_en_b89d1d22.json` 생성
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - PASS 1158, FAIL 0, WARN 0, SKIP 0

## 트랙 B 검토

- **2a (플랫폼 config) — X.** Bundesbank 전용 RSS URL 이고, 재사용 가능한 platform recognizer 로 보기 어렵다.
- **2b (`--article-url`) — X.** 첫 글 URL 하나를 교정해도 `/en/press` landing 의 nav/sidebar 후보 오인은 유지된다.
- **2c/2d (probe/prompt/engine) — 보고만.** `article_body_len` 26건, `posts_nonempty` 95건이 누적되어
  `track_b_trigger=true` 이고, deferred 쪽도 `static_variant_rows_not_promoted`/RSS 관련 후보가 trigger 상태다.
  다만 이번 요청 범위는 이 slug/host 의 fix surface 로 제한되어 있어 shared recognizer/engine/probe/prompt 변경은 하지 않았다.
  별도 Track B 작업에서는 fetch-검증된 RSS 후보가 있고 top HTML candidates 가 nav/sidebar 일 때 feed strategy 를
  더 강하게 선택하는 방안을 검토할 수 있다.
- **2e (수동 config) — O.** 단일 사이트 공식 RSS 로 `posts_nonempty` 를 안정적으로 만족한다.

일반화 안 되는 이유: `633306/feed.rss` 는 Bundesbank press landing 의 사이트 전용 feed 이며, generic RSS 우선
정책은 HTML 본문 board 를 feed summary 로 축소할 수 있어 별도 설계가 필요하다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `article_body_len` 26건, `posts_nonempty` 95건, RSS/deferred 후보 trigger 상태. 이번 작업에서는 shared 변경 보류.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 10건, register baseline 10건, probe_smoke stage 3/5 PASS.
5. **outcome=handcrafted**: 단일 사이트 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` XML parsing 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
