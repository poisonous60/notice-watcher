---
slug: host_cambridge-org_core_9f561f6b
url: https://www.cambridge.org/core/what-we-publish/journals
status: ✅ playwright_html journal directory registered
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [capability_blocked, posts_nonempty]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [publishers, academic-journals, playwright, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

Cambridge Core journal directory는 httpx batch에서 anti-bot/posts0 계열로 남았지만, 현재 `playwright_html` + stealth 렌더에서는 정상 HTML과 journal list row가 나온다.

## 무엇을 바꿨나

`configs/host_cambridge-org_core_9f561f6b.json` 추가.

- `wait_selector`: `li.product-list-entry a.title[href^='/core/journals/']`
- `row_selector`: `li.product-list-entry`
- `post_id`: `/core/journals/<slug>`
- body는 journal directory라 비워도 정상으로 처리

## 검증

- live render: HTTP 200, final URL `https://www.cambridge.org/core/publications/journals`
- selector sample: `Acta Neuropsychiatrica`, `Acta Numerica`, `Advances in Applied Probability`
- row count: 429 journal entries

## outcome = handcrafted

사이트별 journal directory selector를 수동으로 작성했다. generic probe/engine 개선은 없다.

## 트랙 B / 후속

일반화 후보 없음. Cambridge 전용 DOM(`product-list-entry`, `a.title`)에 맞춘 config다.
