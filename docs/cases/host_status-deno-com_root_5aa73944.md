---
slug: host_status-deno-com_root_5aa73944
url: https://status.deno.com/
status: ✅ 등록 (Statuspage.io Atom history feed 사용)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, rss_feed_available, statuspage_history_atom]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/statuspage.py]
tags: [statuspage, atom, rss, feed, batch-2026-05-21-misc]
---

## 무엇이 일어났나

`https://status.deno.com/` root 는 정적 HTML 반복 후보가 subscribe/email 메뉴 쪽으로 잡혔다.
자동 생성은 `/ko-kr/history/1` HTML selector 와 `a[href*='/history/']` 방향으로 3회 시도했지만
모두 `posts_nonempty: 0건` 이었다.

probe 의 `feed_candidates.json` 에는 `https://status.deno.com/feed` 가 검증된 XML 후보로 잡혀
있었고, 직접 확인한 `https://status.deno.com/history.atom` 은 Statuspage.io incident history
Atom feed 로 26개 `entry` 를 제공했다.

## 조치

- `configs/host_status-deno-com_root_5aa73944.json`
  - `strategy: httpx_html`
  - `list.url_template: https://status.deno.com/history.atom`
  - `row_selector: entry`
  - `post_id=id`, `title=title`, `published_at=published`, `summary=content`, `url=link[rel="alternate"]`
  - incident detail page 는 `.prose`/`main` 으로 본문 추출
- `engine/recognizers/statuspage.py`
  - `/history.atom` 과 `/history.rss` 직접 URL 만 known-platform 으로 인식한다.
  - root URL 은 false-positive 위험이 커서 매칭하지 않는다.

## 검증

- config schema validation PASS.
- `recognize('https://status.deno.com/history.atom')` -> `statuspage`.
- `register.py --config configs/host_status-deno-com_root_5aa73944.json` PASS, baseline 26건.
- 첫 글 본문 fetch: 274 chars.

## 트랙 B

Statuspage root 자동 dispatch 는 이번 allow-list 밖인 probe-detect/register merge가 필요하다.
대신 direct feed URL recognizer 를 추가해 사용자가 `/history.atom` 또는 `/history.rss` 를 넣는
반복 케이스는 probe 없이 처리한다.
