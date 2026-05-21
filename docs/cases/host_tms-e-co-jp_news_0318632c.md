---
slug: host_tms-e-co-jp_news_0318632c
url: https://www.tms-e.co.jp/news/
status: 🧩 수동 config — TMS official RSS feed 로 baseline 10건 등록
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, wrong_first_article, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [tms, rss, not-found-shell, sidebar-candidates]
---

## 무엇이 일어났나

`/news/` 는 HTTP 200 으로 열리지만 실제 본문은 `Not Found` shell 이다. probe 의 반복 후보는
`ul.acms-list-group > li` 로 잡혔고, 첫 글 URL 도 `https://www.tms-e.co.jp/company/topmessage/`
였다. 이 후보는 글 목록이 아니라 회사정보/카테고리 사이드바다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`
- `[warn] matches_probe_first_article: probe first_article_url='https://www.tms-e.co.jp/company/topmessage/' 와 일치하는 글 URL 없음`
- `[warn] count_ballpark: 0건 (probe 후보 child_count≈13)`

`diagnosis.json` 은 `정적 HTTP로 충분` 이라고 봤지만, 정적 HTML 안에서 실제 news row 는 없었다.
대신 `feed_candidates.json` 이 head alternate RSS 를 찾았다.

```json
{
  "source": "head-alternate",
  "type": "application/rss+xml",
  "title": "RSS 2.0",
  "url": "https://www.tms-e.co.jp/rss2.xml"
}
```

## 픽스

`configs/host_tms-e-co-jp_news_0318632c.json` 을 RSS 기반 `httpx_html` config 로 작성했다.

- 목록: `https://www.tms-e.co.jp/rss2.xml`, `row_selector: channel > item`
- `post_id`: RSS `guid` 에서 `https://www.tms-e.co.jp/` prefix 를 제거한 stable path
- `title/url/published_at/category/summary`: RSS `title/link/pubDate/category/description`
- 본문: RSS 항목이 외부 작품 사이트나 sparse update 를 가리키는 경우가 있어 `body_empty_acceptable: true`

RSS 는 사이트 전체 update feed 라서 `/news/` 의 빈 HTML shell 보다 운영상 유효한 최신 항목을 제공한다.
다만 dedicated platform 이 아니라 이 host 의 단일 config 로 제한했다.

## 회귀 검증

- `python -c "from engine.recognizers import recognize; print(recognize('https://www.tms-e.co.jp/news/'))"`
  - `None`
- preflight 영향 변경 검사
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 3개: `alltitles/2020s/entry-26191.html`, `alltitles/2020s/entry-26190.html`,
    `alltitles/anpanman/entry-26181.html`
  - 첫 글 `fetch_article()` body length 0, config 에서 body empty 허용
- `python scripts/register.py --config configs/host_tms-e-co-jp_news_0318632c.json`
  - baseline 10건 등록
  - `output/poll_state/host_tms-e-co-jp_news_0318632c.json` 생성

## 트랙 B 검토

- **2a (플랫폼 config) — X.** `www.tms-e.co.jp/rss2.xml` 은 단일 사이트 RSS 이고, 같은 URL 형태의
  재발 source 가 없다.
- **2b (`--article-url`) — X.** 실제 `/news/` HTML 에 news article row 가 없어서 첫 글 URL 교정으로 풀
  문제가 아니다.
- **2c/2d (probe/prompt/engine) — 보류.** `feed_candidates` 는 이미 probe 가 추출했고, RSS 활용 실패는
  누적 trigger 상태다. 하지만 이번 요청의 fix surface 는 단일 slug/host 로 제한되어 있어 shared
  recognizer/engine/prompt 변경은 하지 않았다. 별도 Track B 작업에서는 head alternate RSS 후보를
  HTML 후보가 sidebar/nav-only 일 때 더 강하게 선택하게 하는 방안을 검토할 수 있다.
- **2e (수동 config) — O.** 단일 사이트의 공식 RSS 로 posts_nonempty 를 안정적으로 만족한다.

일반화 안 되는 이유: TMS 사이트 전용 RSS feed 를 쓰는 단일 config 이며, generic 추론이나 플랫폼
dispatch 를 개선하지 않는다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 71건, `feed_candidates` 3건, `feed_candidates|RSS|rss` signal 46건.
   RSS Track B 는 trigger 상태지만 이번 slug 작업에서는 shared 변경을 하지 않았다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 10건, register baseline 10건.
5. **outcome=handcrafted**: 단일 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` XML parsing 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
