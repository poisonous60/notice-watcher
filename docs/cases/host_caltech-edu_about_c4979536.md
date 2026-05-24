---
slug: host_caltech-edu_about_c4979536
url: https://www.caltech.edu/about/news
status: 🧩 수동 config — Caltech news static teasers로 baseline 10건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [article_body_len, nav_first_article, selector_scope]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, caltech, news, html]
---

## 무엇이 일어났나

preflight: miss — 이 worktree에는 `output/poll_state/host_caltech-edu_about_c4979536.FAILED.json` 와 `output/probe/host_caltech-edu_about_c4979536/` 가 없었다. 사용자 전달 실패 요지는 `article_body_len 0` 이고, probe 의 첫 글 힌트가 nav/sidebar 쪽으로 기울어 `tuning-into-quantum-sounds` 본문 selector 를 못 잡은 것이다.

라이브 확인 결과 목록 페이지 자체에는 `div.article-teaser` 반복 카드가 있고, 내부 제목 링크가 `/about/news/<slug>` 로 안정적이다. 외부 Caltech Magazine 링크도 섞이므로 `row_required_selector` 로 `/about/news/` 링크만 받았다.

## 픽스

`configs/host_caltech-edu_about_c4979536.json` 을 `httpx_html` 로 작성했다.

- 목록: `div.article-teaser`
- ID/URL/title/date: teaser 내부 제목 링크와 `.article-teaser__published-date__date`
- 본문: article page 의 `main`

robots.txt 는 `/about/news` 를 허용하고 `Crawl-delay: 10` 을 선언하므로 `polite_sleep` 10-12초를 둔다.

## 회귀 검증

- `python scripts/register.py --config configs/host_caltech-edu_about_c4979536.json` → baseline 10건, rc=0
- `make_adapter` 손실행 → list 10건, 첫 글 body 23863자

## 트랙 B 검토

- 2a 인식기: X. Caltech 단일 Drupal/사이트 구조라 범용 플랫폼 아님.
- 2b `--article-url`: X. 글 URL 교정보다 selector scope 문제가 핵심.
- 2c/2d probe/prompt: 보류. nav-first 신호는 다른 케이스에도 있으나 여기서는 단일 config 로 충분하다.
- 2e 수동 config: O.

일반화 안 되는 이유: Caltech 고유 teaser 클래스와 robots Crawl-Delay 값만 반영한 단일 사이트 config 다.
