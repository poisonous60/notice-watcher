---
slug: host_cochranelibrary_root_7dafdb29
url: https://www.cochranelibrary.com/
status: ✅ playwright_html featured reviews registered from root
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [publishers, medical-reviews, playwright, board-ness, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

Cochrane Library root는 all-journal directory는 아니지만, 요청 URL 안에 featured Cochrane Review carousel이 있고 `playwright_html`로 review links가 렌더된다.

## 무엇을 바꿨나

`configs/host_cochranelibrary_root_7dafdb29.json` 추가.

- `wait_selector`: `div.mySlides.fade a[href*='/cdsr/doi/']`
- `row_selector`: `div.mySlides.fade`
- `post_id`: `/cdsr/doi/<doi>`
- title에서 carousel CTA `Read Review` 제거

## 검증

- live render: HTTP 200, title `Cochrane reviews | Cochrane Library`
- selector sample: `Amyloid-beta-targeting monoclonal antibodies for people with Alzheimer's disease`, `Intermittent fasting for adults with overweight or obesity`, `Methods of induction of labour`
- visible row count: 3 featured reviews

## outcome = handcrafted

root page의 반복 review 카드 selector를 수동으로 작성했다. all-journal directory가 아니므로 board scope는 `featured-reviews`로 제한했다.

## 트랙 B / 후속

일반화 후보 없음. Cochrane root의 carousel 구조에 맞춘 수동 config다.
