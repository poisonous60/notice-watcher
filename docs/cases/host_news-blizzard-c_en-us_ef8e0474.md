---
slug: host_news-blizzard-c_en-us_ef8e0474
url: https://news.blizzard.com/en-us/
status: ✅ 수동 config (/api/news Contentstack feed, 24건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [board_shape_gate_rejected, spa_no_article_links]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [blizzard, news, contentstack, spa, api-discovery]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch run 2026-05-19 에서 board_shape gate_reject. 정적 HTML 7KB SPA shell — article 링크 0개. probe 가 `first_article_url=None`.

## API 발견

`/rss /feed /news.rss /atom.xml` 다 404. `/api/news` 200 → Contentstack-style JSON 58KB.

응답 구조:
```
{
  "layoutId": "...",
  "sections": [...],
  "feed": {
    "contentItems": [
      {
        "contentId": "blt...",
        "contentType": "blogs",
        "properties": {
          "title": "...",
          "newsId": "24276957",
          "newsUrl": "https://news.blizzard.com/en-us/article/24276957/hotfixes-may-15-2026",
          "newsSlug": "hotfixes-may-15-2026",
          "lastUpdated": "2026-05-16T01:30:00Z",
          "summary": "...",
          "category": ...
        }
      }
    ]
  }
}
```

## 픽스

handwritten config. list_path=`feed.contentItems`, post_id=`properties.newsId`, url=`properties.newsUrl`. URL 자체 absolute 라 url_template 안 씀. article body 는 fetch_kind=html (newsUrl 따라가서 `article` selector 추출).

상세: `infra_catalog_batch_rev4_2026-05-19.md`.

## 후속 (2026-05-27): REJECTED — upstream /api/news 영구 500

BROKEN 큐 (cb=6) 복구 작업 중 `/api/news` endpoint 가 5일+ 연속 HTTP 500 으로 죽어 있음 확인. polling 영구 중단.

**live 증거 (2026-05-27)**:
- `GET https://news.blizzard.com/en-us/api/news` → `HTTP/1.1 500 Internal Server Error`, body=`Internal Server Error` (21 bytes, `text/plain`).
- 4회 retry + browser headers 동일 500.
- 대안 endpoint 탐색: `/en-us/feed` → 307 → 404 / `/en-us/rss` → 404 / HTML `/en-us/` → 200 OK 9.5KB (SPA shell, `newsId`/`/api/` 노출 X).
- 도메인 자체는 살아 있음. 오직 `/api/news` 만 죽음.

**N100 jobs reprobe history** (`bot.sqlite3`): 2026-05-22 ~ 2026-05-25 매일 rc=5 (job id 1439, 1583, 2147, 2166, 2184). **5일 연속** capability_blocked.

**Track B 6-layer all miss** — engine 어디 박아도 dead upstream endpoint 못 살림. **Track A miss** — HTML SPA shell 만 살아 있어 손-config 짤 source 없음.

**terminal action** (`_save_rejected`, learn=False):
- reason: `capability_blocked: upstream /api/news endpoint returning HTTP 500 for 5+ days (2026-05-22 ~ 2026-05-27), no alternative endpoint found. HTML shell 200 OK but no newsId/api exposure.`
- sibling cleanup 자동 (state.json/BROKEN.json/triage_queue).

**rollback**: 향후 endpoint 복구 시 `ssh $DEPLOY_HOST 'rm output/poll_state/host_news-blizzard-c_en-us_ef8e0474.REJECTED.json'` + `/watch` 재요청.
