---
slug: host_bnm-gov-my_press-release_315ff7ab
url: https://www.bnm.gov.my/press-release
status: 🧩 수동 config — BNM Press Releases 실제 목록 경로 /pr 렌더 테이블로 baseline 30건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, wrong_list_url, waf_js_challenge]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [bnm, central-bank, press, liferay, waf, playwright]
requested_by: batch
---

## 무엇이 일어났나

사용자 입력 URL `https://www.bnm.gov.my/press-release` 는 AWS WAF JavaScript 검증 뒤에 404 로 떨어진다.
probe digest 도 `first_article_url: null`, HTML/API/hydration 후보 0건을 기록했고, 자동 생성은
`financialmarkets.bnm.gov.my/announcements-highlights` 로 방향이 빗나간 config 를 만들었다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`

`diagnosis.json`:

- `verdict: 정적 HTTP로 충분`
- `recommended_strategy: httpx (S1.H3)`
- `list_candidates: HTML 0건, JSON API 0건, hydration 0건`
- HAR 첫 4xx: `404 https://www.bnm.gov.my/press-release`

렌더링된 공식 홈 메뉴에서는 Press Releases 링크가 `https://www.bnm.gov.my/pr` 로 노출되고, 이 경로는
`https://www.bnm.gov.my/press-release-2026` 으로 이동한다. 해당 페이지에는 최신 press release 목록이
`Date / Title` 테이블로 렌더된다.

## 픽스

`configs/host_bnm-gov-my_press-release_315ff7ab.json` 을 `playwright_html` config 로 작성했다.

- 원본 URL: `https://www.bnm.gov.my/press-release`
- 실제 목록 URL: `https://www.bnm.gov.my/pr`
- wait selector: `tbody tr a[href*='/-/']`
- row: `tbody tr`, 내부 글 row 만 `row_required_selector: a[href*='/-/']` 로 유지
- `post_id`: 글 URL 의 `/-/<slug>`
- `title/url/published_at`: 두 번째/첫 번째 table cell 에서 추출
- 본문: 글 페이지의 `.journal-content-article`

AWS WAF JavaScript challenge 를 통과해야 렌더 DOM 을 안정적으로 얻을 수 있어 `httpx_html` 대신
`playwright_html` 을 사용했다.

## 회귀 검증

- recognizer preflight
  - `recognize('https://www.bnm.gov.my/press-release')` -> `None`
- preflight 영향 변경 검사
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 글: `international-reserves-of-bank-negara-malaysia-as-at-15-may-2026`
  - 첫 글 body length: `6141`
- `python scripts/register.py --config configs/host_bnm-gov-my_press-release_315ff7ab.json`
  - baseline 30건 등록
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - 별도 검증 단계에서 실행

## 트랙 B 검토

- **2a (플랫폼 config) — X.** Liferay 기반 페이지지만 이번 문제는 BNM 의 dead alias `/press-release`
  와 실제 메뉴 경로 `/pr` 의 차이다. 일반 platform recognizer 로 확장하기엔 host-specific 하다.
- **2b (`--article-url`) — X.** 실패 원인은 첫 글 오인이 아니라 목록 URL 자체의 404 와 WAF 렌더링이다.
- **2c/2d (probe/prompt/engine) — 보류.** 사용자가 이번 slug/host fix surface 로 범위를 제한했고,
  recognizer/engine/probe/prompt Track B 는 별도 작업으로 분리하라고 지시했다.
- **2e (수동 config) — O.** 단일 host 의 실제 press 목록 경로와 table selector 로 해결된다.

일반화 안 되는 이유: `www.bnm.gov.my/pr` 는 BNM 사이트 메뉴의 host-specific alias 이며, dead alias 를
공식 메뉴 경로로 치환하는 규칙은 다른 Liferay 사이트에 바로 적용하기 어렵다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: 사용자 HARD STOP 으로 `scripts/cases_index.py query` 실행 금지. INDEX/DB backfill 도 미실행.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 목록 10건/본문 6141자, register baseline 30건.
5. **outcome=handcrafted**: 단일 수동 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `playwright_html` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
