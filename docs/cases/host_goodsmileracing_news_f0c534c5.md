---
slug: host_goodsmileracing_news_f0c534c5
url: https://www.goodsmileracing.com/news/
status: ✅ preflight b-hit 회복 + config 등록 (baseline 10건, httpx_html RSS)
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty, blocked_bot]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [goodsmileracing, wordpress, rss-fallback, cloudfront-empty-body, preflight-b-hit]
---

## 무엇이 일어났나

`/watch https://www.goodsmileracing.com/news/` batch gen_fail. 실패 당시 마지막 자동 config 는 `https://www.goodsmileracing.com/rss` 를 XML처럼 보려 했지만 `httpx_html` row selector 가 0건이라 `[FAIL] posts_nonempty: 0건` 으로 끝났다.

probe 산출물 기준 HTML 진입은 불안정했다. `diagnosis.json` 은 `S1.H2/H3/H4/Hcap` 에서 redirect loop, `S4` 에서 CloudFront 302 + 빈 body 39 bytes 를 기록했고, verdict 는 `분류 보류`였다. 다만 `feed_candidates.json` 에 공개 feed 후보 `https://www.goodsmileracing.com/rss`, `https://www.goodsmileracing.com/feed` 가 있었고 robots.txt 는 `/wp-admin/`, `/wp-includes/` 만 막았다.

preflight: `b-hit — host_goodsmileracing_news_f0c534c5 [27ed350, 5665fa8]`. 실패 이후 영향 영역 commit 이 있어 `python scripts/register.py --reuse-probe "https://www.goodsmileracing.com/news/"` 를 먼저 실행했고, 현재 generator 가 공개 RSS/Atom fallback 으로 `https://www.goodsmileracing.com/feed` 기반 config 를 생성해 2번째 attempt 에서 통과했다.

## 무엇을 바꿨나

`configs/host_goodsmileracing_news_f0c534c5.json` 생성. `strategy=httpx_html`, list는 WordPress RSS `item` row, `guid/link/title/pubDate/description` 기반으로 `post_id/title/url/published_at/summary` 를 뽑는다.

article은 `body_empty_acceptable:true` 와 빈 `content` 로 둔다. 실제 등록 결과도 본문 0자 경고를 냈으므로, 알림은 제목과 URL 중심으로 동작한다.

## Track B 검토

새 probe/schema/prompt/recognizer 변경은 하지 않았다. `posts_nonempty` 누적 query 는 `track_b_trigger=true` 였지만, 이번 케이스는 실패 이후 이미 들어온 feed fallback 경로로 회복된 stale 큐다. HTML 목록 진입 자체는 CloudFront 빈 body/redirect loop 때문에 안정적인 selector 후보가 없고, 공개 feed 후보가 fetch 검증되어 가장 작은 해결책이었다.

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://www.goodsmileracing.com/news/"` → PASS, baseline 10건.
- `python scripts/register.py --config configs/host_goodsmileracing_news_f0c534c5.json` → PASS, baseline 10건, 본문 0자 경고.
- `validate_config` → OK.
- make_adapter 손 실행 → list 10건, 최신 3건 post_id/title/url/published_at 정상.
- `python scripts/probe_smoke.py --stage 3` → PASS 186, FAIL 0.
- `python scripts/probe_smoke.py --stage 5` → PASS 884, FAIL 0.

## 영향 범위

단일 config 추가만 했다. N100 코드 변경, recognizer 변경, prompt 변경, probe 변경은 없다. `docs/cases/INDEX.md` 와 cases DB backfill 은 이번 위임 지시상 건드리지 않았다.
