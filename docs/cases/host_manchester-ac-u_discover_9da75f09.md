---
slug: host_manchester-ac-u_discover_9da75f09
url: https://www.manchester.ac.uk/discover/news/
status: 🧩 수동 config — Manchester Newsroom RSS로 baseline 30건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [post_id_unique, nav_first_article, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, manchester, rss, presspage]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `post_id_unique` 불일치와 nav first_article 이다.

`/discover/news/` 는 현재 `/about/news/` 로 redirect 된다. HTML 안에는 PressPage 위젯과 여러 카테고리 블록이 섞여 있고, 같은 링크가 이미지/제목/도구 영역에 반복된다. 페이지는 최신 뉴스 RSS 링크 `https://www.manchester.ac.uk/about/news/tagfeed/en/tags/headlines` 를 제공한다.

## 픽스

`configs/host_manchester-ac-u_discover_9da75f09.json` 을 RSS 기반 `httpx_html` 로 작성했다.

- 목록: RSS `item`
- ID: `link` 의 `/about/news/<slug>/`
- title/url/published_at/summary: `title/link/pubDate/description`
- 본문: linked article page 의 `main`

source remap 은 같은 사이트가 노출한 RSS endpoint 로 제한했다. robots.txt 에 Crawl-Delay 는 없고 대상 feed/article 경로는 허용된다.

## 회귀 검증

- `python scripts/register.py --config configs/host_manchester-ac-u_discover_9da75f09.json` → baseline 30건, rc=0
- `make_adapter` 손실행 → list 30건, 첫 글 body 32219자

## 트랙 B 검토

- 2a 인식기: X. PressPage RSS를 쓰지만 사이트별 feed URL 이라 인식기 일반화는 과함.
- 2b `--article-url`: X. 중복 ID와 목록 source 선택 문제.
- 2c/2d probe/prompt: 보류. RSS 우선 일반화는 body richness/HTML board 축소 위험이 있어 별도 설계 필요.
- 2e 수동 config: O.

일반화 안 되는 이유: `/tagfeed/en/tags/headlines` 는 Manchester Newsroom 고유 feed 다.
