---
slug: host_uio-no_english_fa764053
url: https://www.uio.no/english/about/news-and-events/news/
status: 🧩 수동 config — UiO Atom feed로 baseline 24건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, atom_feed_available, first_article_hint]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, uio, atom, news]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `posts_nonempty 0` 이지만 사용자가 head 의 `<link rel=alternate type=application/atom+xml href=...?vrtx=feed>` 를 힌트로 제공했다.

제출 목록의 정적 HTML에도 글이 있으나, 공식 Atom feed 가 더 안정적으로 `entry/title/link/published/summary` 를 제공한다.

## 픽스

`configs/host_uio-no_english_fa764053.json` 을 Atom 기반 `httpx_html` 로 작성했다.

- 목록: `https://www.uio.no/english/about/news-and-events/news/?vrtx=feed`
- ID: alternate link 의 `/news/YYYY/<slug>.html`
- 본문: linked article page 의 `main`

robots.txt 는 feed/article 경로를 허용하고 Crawl-Delay 는 없다.

## 회귀 검증

- `python scripts/register.py --config configs/host_uio-no_english_fa764053.json` → baseline 24건, rc=0
- `make_adapter` 손실행 → list 24건, 첫 글 body 7766자

## 트랙 B 검토

- 2a 인식기: X. Vortex/UiO feed URL 은 사이트별.
- 2b `--article-url`: X. feed 사용으로 목록과 글 링크를 동시에 안정화.
- 2c/2d probe/prompt: 보류. rel=alternate feed 우선 일반화는 별도 RSS/Atom 정책 설계 필요.
- 2e 수동 config: O.

일반화 안 되는 이유: `?vrtx=feed` 는 UiO 사이트의 CMS feed endpoint 다.
