---
slug: host_helsinki-fi_en_caf63f4e
url: https://www.helsinki.fi/en/news
status: 🧩 수동 config — Helsinki rendered news cards로 baseline 3건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, nav_first_article, rendered_cards]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, helsinki, news, playwright]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `posts_nonempty 0` 과 first_article 이 faculty/menu page 로 잡힌 것이다.

정적 HTML은 메뉴 shell 에 가까워 `/index.php/en/news/...` navigation 링크만 많이 보인다. Playwright 렌더 후에는 `article.hy-general-list-item` 카드가 나타나며, 각 카드의 `a.hy-general-list-item__link` 가 실제 `/en/news/<category>/<slug>` 글이다.

## 픽스

`configs/host_helsinki-fi_en_caf63f4e.json` 을 `playwright_html` 로 작성했다.

- 목록: `article.hy-general-list-item`
- wait: rendered card link
- ID/URL/title/date/category/summary: card 내부 링크, h3, meta/date, description
- 본문: rendered article page 의 `body`

robots.txt 는 `/en/news` 를 허용하고 `Crawl-delay: 2` 를 선언하므로 4-6초 sleep 을 둔다.

## 회귀 검증

- `python scripts/register.py --config configs/host_helsinki-fi_en_caf63f4e.json` → baseline 3건, rc=0
- `make_adapter` 손실행 → list 3건, 첫 글 body 330079자

## 트랙 B 검토

- 2a 인식기: X. Helsinki 고유 rendered card 클래스.
- 2b `--article-url`: X. 정적 목록 source 가 메뉴 shell 인 것이 핵심.
- 2c/2d probe/prompt: 보류. SPA/render 필요 패턴이지만 engine 변경 없이 `playwright_html` config 로 해결.
- 2e 수동 config: O.

일반화 안 되는 이유: rendered selector 가 Helsinki 디자인 시스템 클래스에 묶여 있다.
