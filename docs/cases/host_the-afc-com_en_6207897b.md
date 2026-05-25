---
slug: host_the-afc-com_en_6207897b
url: https://www.the-afc.com/en/about_afc/news.html
status: ✅ 수동 config 등록 (RSS fallback, body optional)
outcome: handcrafted
date: 2026-05-25
requested_by: sports-batch
failure_keys: [article_body_len, brittle_article_selector, rss_available]
fix_layer: none
config_strategy: rss
adapters_changed: []
engine_files_touched: []
tags: [afc, sports, hand-config, rss, body-optional]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 없음. `triage.py show` 는 probe 산출물 부재를 보고했다.

제출 URL 은 현재 `https://www.the-afc.com/en/national/afc_asian_cup/news.html` 로 redirect 된다. HTML 안에는
SEO footer 형태의 news text 가 있지만 article body selector 가 brittle 해서 자동 config 의
`article_body_len` 이 실패하기 쉽다. 사이트 루트의 `https://www.the-afc.com/rss` 는 valid RSS 를 반환한다.

## 픽스

`configs/host_the-afc-com_en_6207897b.json` 을 추가했다.

- `strategy`: `httpx_html` over RSS
- `list.url_template`: `https://www.the-afc.com/rss`
- `row_selector`: `item`
- `post_id/title/url/summary`: RSS item fields
- `article.content`: linked HTML 의 `p.seo-footer`, 404 최신 item 은 `skip_status`
- `body_empty_acceptable: true`

## 검증

- schema validation: `OK`
- inline adapter smoke: list 5건, 첫 item 404 skip, 다음 sampled article body 43자
- `register.py --config`: PASS, baseline 10건

## 트랙 B 검토

- 2a 인식기: X — AFC 전용 RSS endpoint 선택이다.
- 2b article URL 교정: X — RSS link 는 실제 public URL 이지만 최신 festive greeting item 이 404 를 반환했다.
- 2c/2d probe/prompt: allow-list 밖이라 변경하지 않았다.
- 2e 수동 config: 적용.

일반화 안 되는 이유: RSS source 는 단일 host 전용이다. feed description 을 article body 로 승격하는 generic
engine 어휘가 없어서 config 만으로는 full body 보장이 어렵다.

Root-cause/tradeoff: HTML article selector가 brittle 하고 RSS 최신 일부 link 는 404다. RSS 목록 수집은
안정적이지만 본문은 optional warning 경로로 둔다.
