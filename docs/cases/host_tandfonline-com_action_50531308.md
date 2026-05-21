---
slug: host_tandfonline-com_action_50531308
url: https://www.tandfonline.com/action/showPublications
status: ✅ playwright_html all-journals directory registered
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, board_shape_check]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [publishers, academic-journals, playwright, board-ness, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

bare `showPublications` URL은 Taylor & Francis home으로 redirect되어 journal rows가 없다. journal directory는 같은 action endpoint에 `pubType=journal&ejf=on`을 붙인 URL에서 렌더된다.

## 무엇을 바꿨나

`configs/host_tandfonline-com_action_50531308.json` 추가.

- `url_template`: `https://www.tandfonline.com/action/showPublications?pubType=journal&ejf=on`
- `wait_selector`: `li.searchResultItem.browse-result a.ref[href^='/journals/']`
- `row_selector`: `li.searchResultItem.browse-result`
- `post_id`: `/journals/<journal-code>`

## 검증

- live render: HTTP 200, title `Taylor & Francis Online - All Journals`
- selector sample: `a/b: Auto/Biography Studies`, `The AAG Review of Books`, `Accountability in Research`
- visible page size: 10 journal rows

## outcome = handcrafted

사이트별 A-Z directory selector를 수동으로 작성했다.

## 트랙 B / 후속

일반화 후보 없음. bare action URL을 그대로 게시판으로 보지 않고 canonical journal-list query를 사용한 board-ness 보정이다.
