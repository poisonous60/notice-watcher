---
slug: host_atptour-com_en_3dfed836
url: https://www.atptour.com/en/news
status: ✅ 수동 config 등록 (playwright_html list, body optional)
outcome: handcrafted
date: 2026-05-25
requested_by: sports-batch
failure_keys: [article_body_len, capability_blocked, cloudflare_challenge]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [atp, sports, hand-config, playwright-html, cloudflare, body-optional]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 없음. `triage.py show` 는 probe 산출물 부재를 보고했다.

plain httpx 는 ATP news 에서 Cloudflare challenge HTML 을 받는다. headless Chromium 은 목록 페이지를 렌더하고
`div.atp_card` news cards 를 볼 수 있다. 다만 같은 browser context 에서 article 로 이동하면 검증 shell 에
머물러 `div.atp_article` 이 비어 `article_body_len` 이 반복된다.

## 픽스

`configs/host_atptour-com_en_3dfed836.json` 을 추가했다.

- `strategy`: `playwright_html`
- `list.url_template`: `https://www.atptour.com/en/news`
- `row_selector`: `div.atp_card` + `row_required_selector` 로 news card 만 필터
- `post_id/url/title/author/category/cover_image`: card 내부 href/text/img
- `article.content`: ATP article body selector 를 두되, Cloudflare article navigation 한계 때문에
  `body_empty_acceptable: true`
- `headless` 는 설정하지 않아 N100 기본값 `true` 를 사용한다.

## 검증

- schema validation: `OK`
- inline adapter smoke: list 5건, sampled article body 0자
- `register.py --config`: PASS, baseline 16건 (`body_empty_acceptable` 경로)

## 트랙 B 검토

- 2a 인식기: X — ATP 전용 Cloudflare + card DOM 이다.
- 2b article URL 교정: X — URL 은 맞고 직접 새 browser context 로는 article 이 열린다.
- 2c/2d probe/prompt: X — 문제는 selector 추론이 아니라 같은 context article navigation 이 challenge shell 로 가는 것.
- 2e 수동 config: 적용.

## escalate (allow-list 밖 공통 개선)

full article body 까지 요구하면 `playwright_html` 이 article fetch 때 새 page/context 를 열거나 Cloudflare 검증 후
selector wait 를 재시도하는 F-layer 엔진 변경이 필요하다. 이번 chunk 는 allow-list 밖 engine 변경 금지라
list polling + body warning 으로 등록했다.

Root-cause/tradeoff: 목록은 render/stealth 로 해결되지만 article body 는 같은 context 이동에서 challenge 에 막힌다.
본문 없이도 새 글 감지는 가능하고, 봇은 baseline body-empty 경고를 유지한다.
