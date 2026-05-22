---
slug: host_archlinux-org_feeds_df19e96b
url: https://archlinux.org/feeds/news/
status: ✅ 등록 완료 (Arch Linux RSS feed, reuse-probe 자동 재생성)
outcome: improved
date: 2026-05-22
fix_layer: D
failure_keys: [posts_nonempty, feed_candidates, article_body_len]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [archlinux, rss, feed, reuse-probe, batch-2026-05-22]
---

## 원인

preflight: b-hit — host_archlinux-org_feeds_df19e96b [a9c5da5].

입력 URL 자체가 `application/rss+xml` feed 였고 probe 도 `feed_candidates=1건` 을 잡았다. 실패 당시 자동 생성은 RSS `item` 행을 한 번 잡았지만 article content selector 가 0자라 `article_body_len` 으로 실패했고, 마지막 시도는 `/news/` HTML 쪽 `article` selector 로 틀어져 `[FAIL] posts_nonempty: 0건` 으로 끝났다.

## 처리

`register.py --reuse-probe "https://archlinux.org/feeds/news/"` 를 재실행했다. 실패 이후 들어온 retry/catalog 변경이 반영된 상태에서 두 번째 생성 시도가 통과했고, `configs/host_archlinux-org_feeds_df19e96b.json` 이 생성됐다.

- `list.url_template: https://archlinux.org/feeds/{board}/`
- `row_selector: item`
- `post_id/title/url/published_at/author/summary` 는 RSS item 필드에서 추출
- article 본문은 `https://archlinux.org/news/{post_id}/` HTML 페이지에서 가져온다

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://archlinux.org/feeds/news/"` → PASS, baseline 10건.
- `python scripts/register.py --config configs/host_archlinux-org_feeds_df19e96b.json` → PASS, baseline 10건.

## 트랙 B

일반화 안 되는 이유: 이번 변경은 새 heuristic/recognizer 없이 기존 retry feedback 개선 뒤 `reuse-probe` 로 회복된 단건이다. RSS/feed generic recognizer 를 새로 추가하지 않았다.
