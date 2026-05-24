---
slug: host_idx-co-id_en_a18762e2
url: https://www.idx.co.id/en/news/press-release/
status: "수동 adapter - IDX Nuxt SSR rowData 사용"
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, matches_probe_first_article, count_ballpark, nuxt_ssr_rowdata, cloudflare_api_block]
fix_layer: F
config_strategy: handwritten
adapters_changed: [IdxPressReleaseAdapter]
engine_files_touched: [adapters/idx_press_release.py, adapters/__init__.py, scripts/poll.py]
tags: [idx, press-release, nuxt, cloudflare, hand-config]
requested_by: batch
---

## 무엇이 일어났나

`https://www.idx.co.id/en/news/press-release/` 는 Nuxt SSR 페이지다. 자동 생성은
`httpx_html` 과 `playwright_html` 방향으로 3회 시도했지만 목록 row 를 얻지 못했다.

진단 인용:

- `last_feedback`: `[FAIL] posts_nonempty: 0건`
- `diagnosis.json verdict`: `BASELINE_BLOCKED / 정적 HTTP로 충분`
- `list_candidates`: top 후보가 `head > link`, `head > meta`, `body > script`, `ul.list-nostyle > li.main-nav__item`
- 실패 케이스: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건` / 목록 추출 실패)
- preflight: `miss - host_idx-co-id_en_a18762e2`

정적 DOM 의 반복 후보는 내비게이션뿐이었다. 실제 게시글 목록은 `window.__NUXT__.fetch[*].table.rowData`
안에 있으며, 첫 항목은 `Id=2632`, `Title="IDX Strengthens Market Resilience and Financial Literacy Through Various Strategic Initiatives"` 로 확인됐다.

## 픽스

`IdxPressReleaseAdapter` 를 추가하고 `configs/host_idx-co-id_en_a18762e2.json` 을 `handwritten` 으로 작성했다.

- 목록: Playwright 로 IDX press release 페이지를 열고 Nuxt SSR payload 의 `table.rowData` 를 읽는다.
- `post_id`: row `Id`
- `title/published_at/summary/cover_image`: row 의 `Title`, `PublishedDate`, `Summary`, `ImageUrl`
- 본문: 상세 API `/api/api/publication/pressrelease/<id>` 는 브라우저 런타임에서도 404, 직접 API 호출은 Cloudflare 403 이므로 row `Summary` 를 HTML 본문으로 사용한다.
- `scripts/poll.py` 의 chromium handwritten 목록에 `IdxPressReleaseAdapter` 를 추가해 polling 동시성 가드가 적용되게 했다.

## 트랙 B 검토

- **2a (인식기) - X.** `www.idx.co.id` 단일 사이트이며 범용 플랫폼 recognizer 로 일반화할 근거가 없다.
- **2b (`--article-url`) - X.** probe 의 첫 글 URL 은 `/en/#0` 내비게이션 오인이라 글 URL 교정으로 해결되지 않는다.
- **2c/2d (probe/prompt/engine) - 보류.** Nuxt `window.__NUXT__` 함수 payload 추출은 generic 개선 후보지만 이번 요청은 단일 slug/host fix surface 로 제한되었다.
- **2e (수동 adapter) - O.** Cloudflare 와 Nuxt SSR function payload 때문에 선언적 config 만으로 안정화하기 어렵다.

일반화 안 되는 이유: `window.__NUXT__` function payload 는 JSON island 가 아니라 실행된 전역 객체이고,
현재 `httpx_json.script_root` 는 JSON 파싱만 지원한다. generic parser 추가는 track B 영역이다.

## 회귀 검증

- `make_adapter` smoke
  - `fetch_list(page_size=3)` -> 3건
  - 첫 글: `2632`, `IDX Strengthens Market Resilience and Financial Literacy Through Various Strategic Initiatives`
  - `fetch_article()` body length 101
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - stage 3: 216 / 216 OK
  - stage 5: 89 파일, 955 케이스, 0 FAIL
  - summary: PASS 1172, FAIL 0

`register.py --config` 는 poll_state/triage side effect 를 만들 수 있어 이번 codex 위임 지시상 실행하지 않았다.

## 자가 점검

1. **자리**: F. 새 손어댑터 + export + chromium polling guard.
2. **이전 케이스**: `scripts/cases_index.py query` 는 사용자 지시로 생략했다.
3. **누구 깰까**: 새 adapter/config 추가와 poll chromium set 확장만 있으므로 기존 사이트 selector/API 영향 0.
4. **검증**: make_adapter smoke, probe_smoke stage 3/5.
5. **outcome=handcrafted**: 단일 사이트 손어댑터이며 generic 추론 개선이 아니다.
6. **fixture**: 새 범용 strategy/heuristic 이 아니라 site-specific adapter 라 probe heuristic fixture 추가 없음.
