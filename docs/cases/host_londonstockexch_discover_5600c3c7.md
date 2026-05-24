---
slug: host_londonstockexch_discover_5600c3c7
url: https://www.londonstockexchange.com/discover/news-and-insights
status: "🧩 손어댑터 — LSE Latest tab public API를 읽어 news-and-insights baseline 등록"
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, spa_api_post_refresh]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/london_stock_exchange.py]
engine_files_touched: []
tags: [london-stock-exchange, lse, news, api, handwritten-adapter]
requested_by: batch
---

## 무엇이 일어났나

대상 URL:

```
https://www.londonstockexchange.com/discover/news-and-insights
```

preflight:

- `preflight: miss — host_londonstockexch_discover_5600c3c7`
- `configs/host_londonstockexch_discover_5600c3c7.json` 없음
- recognizer 매칭 없음
- 실패 이후 `prompts/`, `engine/`, `probe/`, `generate/`, `engine/recognizers/` 변경 없음

`diagnosis.json`은 정적 HTTP 가능으로 보였지만, 정적 HTML 반복 후보에는 실제 글 링크가 없었다. `list_candidates.json`도 `first_article_url=null`, HTML 후보 5건, JSON API 후보 0건이었다.

HAR에는 실제 데이터 소스가 있었다.

- `GET https://api.londonstockexchange.com/api/v1/pages?path=discover/news-and-insights&parameters=`
- `POST https://api.londonstockexchange.com/api/v1/components/refresh`

자동 생성은 렌더 DOM의 `app-page-content article` 계열 selector를 세 번 시도했지만 모두 `[FAIL] posts_nonempty: 0건`으로 끝났다.

## 원인

News and insights 목록은 초기 HTML에 게시글 행으로 박히지 않는다. 페이지 JSON의 `tab-nav`에서 Latest 탭 module id를 얻고, 그 module id들을 `components/refresh`에 POST해야 `exploreStoriesResults` 배열이 내려온다.

현재 선언형 `httpx_json` strategy는 GET JSON만 지원하므로 이 POST refresh 흐름을 config만으로 표현할 수 없다.

## 해결

`LondonStockExchangeNewsAdapter`를 추가했다.

- `GET /api/v1/pages`로 Latest 탭과 module id를 찾는다.
- `POST /api/v1/components/refresh`로 Latest 탭 컴포넌트를 가져온다.
- `exploreStoriesResults[]`를 최신순 목록으로 사용한다.
- `title`, `link`, `datetime`, `text`, `image`, `tags`를 각각 제목, URL, 날짜, 요약, 이미지, 카테고리로 매핑한다.
- 본문은 개별 글의 `GET /api/v1/pages?path=<article>`에서 `storyText`를 가져온다.

config:

```
configs/host_londonstockexch_discover_5600c3c7.json
```

strategy:

```
handwritten / LondonStockExchangeNewsAdapter
```

## 회귀 검증

영향 범위는 새 adapter와 새 config 하나뿐이다. 기존 config가 이 adapter를 참조하지 않으므로 기존 사이트 영향은 0개다.

검증 결과는 작업 로그에 남겼다.

## 일반화 검토

- 2a platform recognizer: X. `londonstockexchange.com` 단일 사이트의 API 컴포넌트 구조다.
- 2b `--article-url`: X. 첫 글 URL 추출 실패가 증상이지만, 원인은 목록 API가 POST refresh 뒤에 있다는 점이다.
- 2c/2d probe 개선: 보류. HAR에는 API가 보이지만, tab id와 module id를 조합해 POST body를 만드는 의미 해석은 사이트별이다.
- 2e handwritten adapter: O. 현재 generic `httpx_json`의 GET-only 어휘로는 표현할 수 없어 작은 adapter가 가장 단순하다.

일반화 안 되는 이유: `tab-nav` 모듈, `contentTabNav`, `components/refresh`, `exploreStoriesResults` 필드 의미가 LSE 사이트 전용이다.

## 자가 점검 (§6)

1. **자리**: F (새 handwritten adapter + config).
2. **이전 케이스**: `posts_nonempty`는 흔하지만 이번 root-cause는 LSE 전용 POST refresh API다.
3. **누구 깰까**: 새 config만 새 adapter를 참조하므로 기존 사이트 영향 0개.
4. **검증**: `register.py --config`와 make_adapter posts_nonempty 확인.
5. **outcome=handcrafted**: dedicated adapter라 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy가 아니라 새 adapter라 stage 3 make_adapter 검증으로 충분.
7. **트랙 B 0건 사유**: 위 §일반화 검토 참조.
