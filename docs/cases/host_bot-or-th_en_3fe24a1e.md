---
slug: host_bot-or-th_en_3fe24a1e
url: https://www.bot.or.th/en/news-and-media/news.html
status: ✅ 수동 config 등록 (playwright_html, baseline 5건)
outcome: handcrafted
date: 2026-05-24
requested_by: batch
failure_keys: [posts_nonempty, nav_only_same_host, js_rendered_list]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [bank-of-thailand, aem, webcomponent, playwright-html]
---

## 무엇이 일어났나

preflight: miss — 기존 `configs/host_bot-or-th_en_3fe24a1e.json` 없음, recognizer 매칭 없음,
실패 시각 이후 `prompts/`, `engine/`, `probe/`, `generate/`, `engine/recognizers/` 변경 없음.

자동 생성은 `httpx_html` 로 `div.related-contents-item` 계열 selector 를 3회 시도했지만
`[FAIL] posts_nonempty: 0건` 으로 끝났다. 정적 HTML 에는 실제 뉴스 row 가 없고
`<bot-listing-page resourcePath="..." type="newsListingResults"/>` webcomponent shell 만 있다.
probe 의 반복 후보도 `nav_only_same_host=true` 로 header/nav 링크만 잡았다.

## 무엇을 바꿨나

단일 사이트 수동 config 를 추가했다.

- `configs/host_bot-or-th_en_3fe24a1e.json`
- strategy: `playwright_html`
- list: `https://www.bot.or.th/en/news-and-media/news.html`
- wait/row selector: `bot-listing-page a[href*='/en/news-and-media/news/']`
- post_id: `/en/news-and-media/news/{id}.html` 의 `{id}` (`mpc/news-...` 같은 하위 path 포함)
- article: 렌더된 글 페이지의 `div.cmp-text`

## 회귀 검증

- 스키마 OK.
- 브라우저 렌더 손 확인:
  - `bot-listing-page a[href*="/en/news-and-media/news/"]` 5건
  - 첫 글 `https://www.bot.or.th/en/news-and-media/news/news-20260519.html`
  - 첫 글 본문 `div.cmp-text` 존재
- `python scripts/register.py --config "configs/host_bot-or-th_en_3fe24a1e.json"` PASS
  - baseline 5건
  - 첫 글 `news-20260519`
  - 날짜 `2026-05-19T00:00:00+07:00`

## 트랙 B 검토

- 2a 인식기: X — Bank of Thailand 단일 AEM site 구조다. 같은 host 반복 요청 전까지
  platform recognizer 는 과하다.
- 2b first_article_url 교정: X — probe first article 이 nav `/en/news-and-media.html` 로 틀렸지만,
  목록 row 자체가 정적 HTML 에 없어서 article URL 교정만으로 해결되지 않는다.
- 2c/2d probe/schema/prompt: 보류 — webcomponent 렌더 목록은 이미 기존 어휘
  `playwright_html + wait_selector` 로 풀린다. 이번 slug 하나 때문에 probe 휴리스틱이나 prompt 를
  넓히면 shared surface 가 커진다.
- 2e 수동 config: 적용 — 렌더 DOM selector 로 목록과 본문을 안정 추출한다.

일반화 안 되는 이유: `<bot-listing-page type="newsListingResults">` 는 이 사이트의 AEM 구현 세부사항이다.
같은 컴포넌트 host 가 2건 이상 누적되면 recognizer 또는 probe hint 후보로 재검토한다.
