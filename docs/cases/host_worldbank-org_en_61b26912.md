---
slug: host_worldbank-org_en_61b26912
url: https://www.worldbank.org/en/news
status: "수동 config - World Bank news landing 의 정적 latest news cards 로 등록"
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, matches_probe_first_article, count_ballpark]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [worldbank, news, static-html, carousel]
requested_by: batch
---

## 무엇이 일어났나

`https://www.worldbank.org/en/news` 는 정적 HTTP 로 접근 가능하고 최신 뉴스 카드도 서버 응답 HTML 안에 있다.
하지만 자동 생성은 존재하지 않는 `div.carousel-wrapper > ul > li` root 를 선택해 목록을 0건으로 추출했다.

진단 인용:

- `last_feedback`: `[FAIL] posts_nonempty: 0건`
- `diagnosis.json verdict`: `정적 HTTP로 충분`
- 실패 케이스: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건` / 목록 추출 실패)
- 분기: 2e 수동 config. probe 산출물에 실제 정적 row 와 본문 selector 가 보이며, 이번 요청은 shared engine/probe/prompt 변경을 금지했다.
- 누적 cross-check: `posts_nonempty` 96건, `matches_probe_first_article` 16건, `count_ballpark` 4건으로 모두 `track_b_trigger=true`.
- preflight: `miss - host_worldbank-org_en_61b26912`

probe 의 실제 정적 후보는 `ul > li.opacity` 5건이었고, saved HTML 에서는 상위 root
`div.carousel-with-button > ul > li` 로 6건을 얻을 수 있었다. live HTTP 응답은 `/ext/en/news` 로 리다이렉트되며
carousel wrapper 없이 dated `/en/news/...` anchor 를 직접 포함한다. 자동 생성기의 `div.carousel-wrapper` 는 같은 페이지에서
매칭 0건이었다.

## 픽스

`configs/host_worldbank-org_en_61b26912.json` 을 `httpx_html` config 로 작성했다.

- 목록: `https://www.worldbank.org/en/news`
- row: dated `a[href^='https://www.worldbank.org/en/news/']`
- 뉴스 index/contacts 링크는 dated path `post_id` regex 로 자연 제외
- `post_id`: canonical World Bank news path
- `title/url/published_at/category`: card anchor 와 URL path 에서 추출
- 본문: article page 의 `article.lp__body_content`

페이지 하단의 `search.worldbank.org` JSON API 도 확인했지만, hidden query 는 publications/brief 등 뉴스 외 문서까지 섞어
`/en/news` landing 의 최신 뉴스 카드와 의미가 달라 이번 config 에 사용하지 않았다.

## 트랙 B 검토

- **2a (인식기) - X.** World Bank 단일 landing 구조이며 플랫폼 recognizer 로 일반화할 근거가 부족하다.
- **2b (`--article-url`) - X.** probe 첫 글은 실제 기사 URL 이고, 실패 원인은 첫 글 오인이 아니라 잘못된 row root 선택이다.
- **2c/2d (probe/prompt/engine) - TODO.** `posts_nonempty`/`matches_probe_first_article`/`count_ballpark` 모두 누적 trigger 상태이고,
  `static_variant_rows_not_promoted` deferred 후보도 trigger 상태다. 다만 이번 요청은 host slug 하나의 fix surface 로 제한되어 있어
  shared recognizer/engine/probe/prompt 변경은 하지 않았다. 별도 Track B 작업에서는 LLM 이 probe top 후보의 `ul > li.opacity`
  또는 live HTML 의 `carousel-with-button` root 를 `carousel-wrapper` 로 바꾸지 않도록 retry feedback/prompt 쪽을 검토할 수 있다.
- **2e (수동 config) - O.** 단일 사이트 정적 HTML row 와 본문 selector 로 해결된다.

일반화 안 되는 이유: 이 config 는 World Bank Edge landing 의 dated news URL 구조와 article body class 에 직접 의존하는
단일 host 수동 config 이며, generic 추론이나 platform dispatch 를 개선하지 않는다.

## 회귀 검증

- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 3개: `/en/news/press-release/2026/04/15/world-bank-group-launches-initiative-to-improve-water-security-for-1-billion-people`,
    `/en/news/press-release/2026/05/19/world-bank-group-to-double-guarantees-for-africa-to-catalyze-investment-create-jobs`,
    `/en/news/statement/2026/05/18/joint-statement-by-seven-multilateral-development-banks-pledging-support-to-address-impacts-of-the-middle-east-conflict`
  - 첫 글 `fetch_article()` body length 4093
- `python scripts/register.py --config configs/host_worldbank-org_en_61b26912.json`
  - baseline 10건 등록
  - `output/poll_state/host_worldbank-org_en_61b26912.json` 생성
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - stage 3: 213 / 213 OK
  - stage 5: 89 파일, 955 케이스, 0 FAIL, coverage 39/39
  - summary: PASS 1169, FAIL 0, WARN 0, SKIP 0

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 96건, `matches_probe_first_article` 16건, `count_ballpark` 4건으로 trigger 상태. 이번 작업에서는 shared 변경 보류.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 10건/body 4093자, register baseline 10건, probe_smoke stage 3/5 PASS.
5. **outcome=handcrafted**: 단일 수동 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
