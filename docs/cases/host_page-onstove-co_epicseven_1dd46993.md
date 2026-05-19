---
slug: host_page-onstove-co_epicseven_1dd46993
url: https://page.onstove.com/epicseven/kr/list/e7kr001
status: ✅ 손-config (api.onstove.com cwms v3.0 article list, 15건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [gen_fail_posts_nonempty, spa_no_article_links]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [onstove, epic-seven, smilegate, cwms, spa, har-xhr-discovery, board-seq-mapping]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch 2026-05-19 에서 gen_fail posts_nonempty. page.onstove.com 의 e7kr001 list 가 정적 HTML 1.18MB 지만 article 카드 모두 JS 로 렌더 (Nuxt 류 SPA). probe 가 `mhy-article-card-wrapper` 비슷한 selector 못 찾음.

## API 발견

N100 에서 Playwright HAR XHR 캡처 (`scripts/_har_xhr.py`) 로 다음 호출 추출:

```
GET https://api.onstove.com/cwms/v3.0/article_group/BOARD/995/article/list?
    interaction_type_code=LIKE,DISLIKE,COMMENT,VIEW&...
```

board_seq=995 = e7kr001 보드. 응답:
```
{
  "code": 0,
  "value": {
    "list": [
      {
        "article_id": "13347605",
        "title": "PC 클라이언트 결제 불가 사전 안내 (05/20 06:00 ~ 10:00)",
        "create_datetime": "1779181201451",  # ms unixtime
        "subtitle": "...",
        "media_thumbnail_url": "...",
        "user_info": {"nickname": "..."},
        ...
      }
    ],
    "total": ..., "next_yn": "Y/N"
  }
}
```

## 픽스

handwritten config. success_when=code==0, list_path=`value.list`, post_id=`article_id`, URL pattern `https://page.onstove.com/epicseven/kr/view/{post_id}`. published_at unixtime_to_iso ms 단위.

## 함정

- board_seq 매핑 (e7kr001 → 995) 은 HAR 에서만 발견됨. catalog 의 path slug 와 다름. 다른 onstove 보드 추가 시 같은 HAR 단계 필요.
- `cwms v3.0 ... /list` 는 default cookies 없이도 200 응답. CSRF/auth 안 박혀 있음 (다른 onstove endpoint 는 Origin 헤더 필요할 수 있음 — Origin/Referer 박아둠).

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
