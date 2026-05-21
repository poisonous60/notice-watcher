---
slug: host_sunrise-inc-co-_news_5275d937
url: https://www.sunrise-inc.co.jp/news/
status: ✅ 수동 config 등록 (SUNRISE root news block, baseline 5건)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [schema_invalid, selector_leading_combinator, wrong_relative_article_url]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [sunrise, hand-config, static-html, selector]
---

## 무엇이 일어났나

`/news/` 는 `https://www.sunrise-inc.co.jp/` 로 200 redirect 되고, 홈의 `#newstopics`
블록에 최신 작품 뉴스가 정적 HTML 로 노출된다. 자동 생성 config 는 그 구조를 거의 맞췄지만
`dt + dd.title` sibling 구조를 `row_selector="#newstopics dl > dt"` 기준으로 풀면서 필드 selector 를
`+ dd.title a` 로 시작하게 만들었다. 이 selector 는 soupsieve 에서 컴파일되지 않아 schema 검증에서
반복 실패했다.

추가로 probe 의 `first_article_url` 은 `/news/` 기준으로 `work/news.php?id=...` 를 urljoin 해
`https://www.sunrise-inc.co.jp/news/work/news.php?id=23631` 로 잡았는데, 실제 글 URL 은
`https://www.sunrise-inc.co.jp/work/news.php?id=23631` 이다.

## 무엇을 바꿨나

단일 사이트 수동 config 를 추가했다.

- 목록 URL 은 redirect 후 실제 보드가 있는 `https://www.sunrise-inc.co.jp/` 로 고정했다.
- 행은 `#newstopics dl > dd.title` 로 잡고 `post_id`, `title`, `url` 을 추출한다.
- 글 URL 은 `https://www.sunrise-inc.co.jp/work/news.php?id={post_id}` template 로 생성한다.
- 본문은 `#news .newsbox .main .txt`, title/category/author/date 는 글 페이지의 `div.newsbox .hd` 에서 enrich 한다.

## 회귀 검증

- `python scripts/register.py --config "configs/host_sunrise-inc-co-_news_5275d937.json"` PASS
  - baseline 5건
  - 예시 post_id: `23631`, `23627`, `23612`

## 트랙 B 검토

- 2a 인식기: X — SUNRISE 단일 사이트의 홈 news block 구조라 플랫폼 recognizer 로 넓힐 대상이 아니다.
- 2b first_article_url 교정: 부분 해당 — 실제 글 URL 기준을 config 에 직접 박았다. 자동 재생성보다 단일 config 가 더 작다.
- 2c/2d probe/schema/prompt: 보류 — `selector_dot_escape_feedback` deferred 는 count 2지만 `track_b_trigger=false` 였다. 이번 케이스의 핵심은 Tailwind dot escape 가 아니라 leading sibling combinator 이며, 즉시 일반화하기엔 표본이 아직 좁다.
- 2e 수동 config: 적용 — static HTML 과 기존 httpx_html 어휘로 충분하다.

일반화 안 되는 이유: `dt/dd` sibling 목록을 config 어휘로 안정 추출할 수는 있지만, 이 사이트는 redirect 된 홈의 특정 `#newstopics` DOM 과 root 기준 article URL template 에 의존한다. 같은 CMS/플랫폼 반복 신호가 없다.
