---
slug: host_jleague-co_news_af0a9ee7
url: https://www.jleague.co/news/
status: ✅ 수동 config 등록 (httpx_html, J.LEAGUE news card rows)
outcome: handcrafted
date: 2026-05-25
requested_by: batch-2026-05-21-sports
failure_keys: [post_id_stable_shape]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [sports, jleague, hand-config, httpx-html, url-slug-id]
---

## 무엇이 일어났나

`https://www.jleague.co/news/` 는 서버 렌더링 HTML 안에 실제 뉴스 목록을 노출하는 게시판이다. probe/AUTO 는
올바른 row 후보 `ul.news-articles-list > li.news-articles-list__item` 를 찾았고, 20건 목록과 첫 글 본문도
확인했지만, 실패 artifact 에서 `[FAIL] post_id_stable_shape` 로 멈췄다.

root-cause: `generate/validate.py` 의 `_STABLE_ID_RE` 는 공백 없는 slug 를 허용하되 길이를 200자로 제한하는데,
J.LEAGUE 일부 URL slug 는 안정적인 canonical article id 이면서도 200자를 넘을 수 있어 false-reject 된다.

screen-out: P1/P2/P3 해당 없음. 이 URL 은 단일 글, soft-404, 빈 feed 가 아니라 정적 HTML 뉴스 목록이다.

## 무엇을 바꿨나

`configs/host_jleague-co_news_af0a9ee7.json` 을 추가했다.

- `strategy`: `httpx_html`
- `list.row_selector`: `ul.news-articles-list > li.news-articles-list__item`
- `post_id`: `a.news-article[href^='/news/']` 의 href 에서 `strip_query_fragment` 후 `/news/([^/?#]+)/?$`
- `title`: `h3.news-article__details__title`
- `url`: 같은 href 를 `https://www.jleague.co` 기준으로 `urljoin`
- `published_at`: `div.news-article__details__post-date` 의 `Mon, 25 May 2026 · 10:43` 부분을 JST ISO8601 로 변환
- `article.content`: 상세 페이지의 `article.news-article` HTML
- `polite_sleep`: 30~35초

## 회귀 검증

- config schema validation PASS.
- 손 실행 `fetch_list(page_size=5)` → 5건, 각 글 title/url/published_at 추출 확인.
- 첫 글 `fetch_article` → body 5528 chars.
- `python scripts/register.py --config "configs/host_jleague-co_news_af0a9ee7.json"` → PASS, baseline 20건.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 1439 / FAIL 0 / WARN 0 / SKIP 0, exit 0.

## 일반화 검토

- 패턴: URL 마지막 segment 가 stable id 인 뉴스 CMS 에서 긴 kebab slug 가 `post_id_stable_shape` cap 을 넘는다.
- 영향: 이번 J.LEAGUE 와 기존 `host_amiami-com_eng_f0c7cc0e` 모두 `post_id_stable_shape` 계열 실패였지만,
  AmiAmi 는 title-derived id 문제였고 J.LEAGUE 는 canonical URL slug 길이 문제라 같은 selector 로 일반화할 수 없다.
- fix layer 후보: F/E 경계. 현재 validator cap 자체가 false-reject 원인이므로 엔진/검증 layer 에서 "URL에서 추출한 canonical slug" 는 길이 cap 을 별도 취급하는 개선이 필요하다.
- 다음 chunk 권장: yes. allow-list 밖인 `generate/validate.py` 또는 관련 validation feedback 변경이 필요하므로 이번 작업에서는 config 로만 닫고 별도 PR/chunk 로 escalate 한다.

## escalate (allow-list 밖 개선 필요)

engine layer fix 필요. `post_id_stable_shape` 가 공백/문장부호가 섞인 title-id 실수를 잡는 목적은 맞지만,
URL path 에서 추출한 dash-separated canonical slug 는 길이가 길어도 안정 ID 일 수 있다. allow-list 가
`configs/` 와 `docs/cases/` 로 제한되어 이번 chunk 에서는 validation cap 조정이나 source-aware 예외를 적용하지 않았다.
