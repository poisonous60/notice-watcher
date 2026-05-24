---
slug: host_ucl-ac-uk_news_3ac1ccc2
url: https://www.ucl.ac.uk/news/
status: ✅ 수동 config 등록 준비 (Funnelback JSON path correction)
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [success_when_path, funnelback_json, data_path]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [gen-fail, batch-2026-05-21-govedu, funnelback, ucl]
---

## 진단

preflight: miss — local `output/probe` / `output/poll_state` artifacts absent, existing config absent, recognizer None.

The failed config checked `success_when` at `response.resultPacket.status`, which is not present in Funnelback JSON. The live UCL page embeds feeds such as `https://cms-feed.ucl.ac.uk/s/search.json?collection=drupal-push-news-news...`.

The working Funnelback contract is:
- success path: `response.returnCode == 0`
- list path: `response.resultPacket.results`
- result URL: `liveUrl`
- title/date/summary metadata: `metaData.FeedTitle`, `metaData.PublishedDate`, `summary`

## 변경

`configs/host_ucl-ac-uk_news_3ac1ccc2.json` uses `httpx_json` against the embedded `cms-feed.ucl.ac.uk` Funnelback endpoint. Article fetch uses a per-item Funnelback `text={post_id}` query and stores the indexed summary as content because the current `httpx_json` strategy does not fetch HTML article pages even when `article.fetch_kind` is `html`.

## 검증

- `make_adapter` live check: 5 posts, first post `news/2026/may/recently-born-generations-may-spend-more-years-poor-health`, first article summary length 241.
- `python scripts/register.py --config "configs/host_ucl-ac-uk_news_3ac1ccc2.json"` PASS, baseline 20 posts.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.

## 트랙 B

No generic Funnelback recognizer added in this batch. The fix is the site-specific path correction requested for UCL; shared Funnelback support would need a separate engine/recognizer change and fixtures.
