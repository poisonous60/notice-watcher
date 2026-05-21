---
slug: host_link-springer-c_search_461b97e6
url: https://link.springer.com/search
status: ✅ playwright_html journal A-Z directory registered via linked journal-list URL
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [board_shape_check, posts_nonempty]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [publishers, academic-journals, playwright, board-ness, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

입력 URL `https://link.springer.com/search` 자체는 빈 generic search form이라 게시판/list가 아니다. 페이지 안의 `Find a journal` / `Journals A-Z` 링크를 따라가면 `https://link.springer.com/journals/a/1`에서 실제 journal directory rows가 나온다.

## 무엇을 바꿨나

`configs/host_link-springer-c_search_461b97e6.json` 추가.

- `url_template`: `https://link.springer.com/journals/a/1`
- `wait_selector`: `li.c-atoz-list__item a.c-atoz-list__link[href*='/journal/']`
- `row_selector`: `li.c-atoz-list__item`
- `post_id`: `/journal/<numeric-id>`

## 검증

- `/search` live render: 검색 폼과 navigation만 있음, journal row 없음
- `/journals/a/1` live render: HTTP 200, title `Journals beginning with A`
- selector sample: `A R I`, `AAPPS Bulletin`, `AAPS Open`, `AAPS PharmSciTech`

## outcome = handcrafted

입력 URL을 그대로 게시판으로 보지 않고, 같은 사이트의 명시적 journal-list URL로 config를 작성했다.

## 트랙 B / 후속

Springer A-Z directory 전용 selector다. `/search`를 게시판으로 통과시키지 않은 것이 board-ness 결정이다.
