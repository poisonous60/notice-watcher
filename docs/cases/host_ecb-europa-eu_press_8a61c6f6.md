---
slug: host_ecb-europa-eu_press_8a61c6f6
url: https://www.ecb.europa.eu/press/html/index.en.html
status: "수동 config - ECB press RSS feed 사용"
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, matches_probe_first_article, count_ballpark, rss_feed_available, foedb_rendered_list]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [ecb, rss, foedb, hand-config]
requested_by: batch
---

## 무엇이 일어났나

`https://www.ecb.europa.eu/press/html/index.en.html` 는
`/press/pubbydate/html/index.en.html` 로 리다이렉트된다. 자동 생성은
`playwright_html` 로 `#addsearch-api-results` / `.foedb-plugin` DOM row 를 기다리는 방향을
3회 시도했지만 실제 검증에서는 글 row 를 얻지 못했다.

진단 인용:

- `last_feedback`: `[FAIL] posts_nonempty: 0건`
- `diagnosis.json verdict`: `정적 HTTP로 충분`
- 실패 케이스: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건` / 목록 추출 실패)
- 분기: 2e 수동 config. 공개 RSS feed 로 선언적 config 가 가능하고 손어댑터는 필요 없다.
- 누적 cross-check: 이번 위임 프롬프트에서 `scripts/cases_index.py query` 실행이 명시 금지되어 생략했다.
- preflight: `miss - host_ecb-europa-eu_press_8a61c6f6`

probe 의 정적 반복 후보는 언어 전환 링크(`#language-values > a.available`)와 내비게이션 링크였다.
실제 페이지의 FOEDB 플러그인은 `/foedb/dbs/foedb/publications.en/...` 정적 JSON DB를 읽어 브라우저에서
목록을 구성한다. 하지만 해당 DB는 버전/hash 경로가 바뀌는 구조라 config 에 직접 박기 부적합하다.

## 픽스

`configs/host_ecb-europa-eu_press_8a61c6f6.json` 을 RSS 기반 `httpx_html` config 로 작성했다.

- 목록: `https://www.ecb.europa.eu/rss/press.html`, `row_selector: item`
- `post_id`: RSS `guid` 의 ECB path
- `title/url/published_at`: RSS `title/link/pubDate`
- 본문: HTML article page 의 `main > .section` fallback chain
- 일부 feed item 이 PDF 를 직접 가리키므로 `article.body_empty_acceptable=true`

## 트랙 B 검토

- **2a (인식기) - X.** ECB 단일 사이트 feed rescue 이며 범용 플랫폼 recognizer 로 일반화할 근거가 부족하다.
- **2b (`--article-url`) - X.** probe 의 첫 글은 언어 링크였지만, 실제 원인은 목록 source 선택 문제다.
- **2c/2d (probe/prompt/engine) - 보류.** FOEDB JSON DB와 RSS 선택은 일반화 후보가 될 수 있지만 이번 요청은 단일 slug/host fix surface 로 제한되었다.
- **2e (수동 config) - O.** 공식 RSS feed 로 posts_nonempty 를 안정적으로 만족한다.

일반화 안 되는 이유: `/rss/press.html` 은 ECB press 영역 전용 feed 이고, FOEDB DB 경로는 버전/hash를 포함해
정적 config 로 쓰기 어렵다. 공유 recognizer/probe 변경은 이번 범위 밖이다.

## 회귀 검증

- `python scripts/register.py --config configs/host_ecb-europa-eu_press_8a61c6f6.json`
  - baseline 15건 등록
  - 첫 3건: `ecb.gc260522~a4812a8f23.en.html`, `ecb.sp260522~f0f11a5f05.en.html`, `ecb.sp260521~ccae6782e3.en.pdf`
- `make_adapter` smoke
  - `fetch_list(page_size=10)` -> 10건
  - 첫 HTML article `fetch_article()` body length 10264
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - stage 3: 202 / 202 OK
  - stage 5: 89 파일, 955 케이스, 0 FAIL
  - summary: PASS 1158, FAIL 0

## 자가 점검

1. **자리**: config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: cross-check 조회는 사용자 지시로 생략.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: register baseline 15건, make_adapter list/body, probe_smoke stage 3/5 PASS.
5. **outcome=handcrafted**: 단일 사이트 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` XML parsing 사용이라 별도 fixture 추가 없음.
