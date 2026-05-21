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
