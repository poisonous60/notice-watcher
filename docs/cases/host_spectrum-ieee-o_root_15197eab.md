---
slug: host_spectrum-ieee-o_root_15197eab
url: https://spectrum.ieee.org/
status: 🧩 수동 config — IEEE Spectrum RSS로 baseline 26건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [post_id_unique, nav_first_article, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, spectrum, ieee, rss]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `post_id_unique` 중복과 nav first_article 이다. 사용자가 head 의 `<link rel=alternate type=application/rss+xml href=/feeds/feed.rss>` 를 힌트로 제공했다.

root page 는 topic/type/nav 링크와 article cards 가 섞여 있어 root selector 가 중복되기 쉽다. 공식 RSS feed 는 `item/title/link/pubDate/description` 을 제공한다.

## 픽스

`configs/host_spectrum-ieee-o_root_15197eab.json` 을 RSS 기반 `httpx_html` 로 작성했다.

- 목록: `https://spectrum.ieee.org/feeds/feed.rss`
- ID: item link path slug
- title/url/published_at/summary: RSS fields
- 본문: article page 의 `article`, fallback `body`

일부 RSS item 은 sponsored/event 외부 링크가 섞일 수 있어 `body_empty_acceptable` 를 둔다. 현재 첫 Spectrum article 은 body 3857자로 정상 추출된다.

## 회귀 검증

- `python scripts/register.py --config configs/host_spectrum-ieee-o_root_15197eab.json` → baseline 26건, rc=0
- `make_adapter` 손실행 → list 26건, 첫 글 body 3857자

## 트랙 B 검토

- 2a 인식기: X. IEEE Spectrum root feed 단일 사이트.
- 2b `--article-url`: X. root nav/duplicate row 문제.
- 2c/2d probe/prompt: 보류. rel=alternate RSS 우선 일반화는 별도 설계가 필요.
- 2e 수동 config: O.

일반화 안 되는 이유: `/feeds/feed.rss` 는 Spectrum 고유 feed 이고 외부/sponsored item 처리가 사이트별이다.
