---
slug: host_mangaplus-shuei_updates_28a3a423
url: https://mangaplus.shueisha.co.jp/updates
status: 🚫 거부 — updates SPA shell 은 열리지만 공개 목록 payload 를 얻지 못함
outcome: rejected
date: 2026-05-22
failure_keys: [posts_nonempty, wrong_first_article, nav_only_candidates, protobuf_api_empty, article_click_403]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [mangaplus, spa, protobuf, api-empty, rejected]
requested_by: batch
---

## 무엇이 일어났나

batch `gen_fail(rc=1)` 로 들어온 케이스다. 제출 URL `https://mangaplus.shueisha.co.jp/updates` 는
HTTP 200 이고 robots.txt 도 전체 허용이지만, 렌더된 DOM 안에 실제 update/title row 가 없다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`
- `[warn] matches_probe_first_article: probe first_article_url='https://mangaplus.shueisha.co.jp/updates' 와 일치하는 글 URL 없음`
- `[warn] count_ballpark: 0건 (probe 후보 child_count≈7)`

`list_candidates.json` 의 반복 후보는 header navigation, footer, SNS 링크뿐이다. 같은 host 후보도
`/updates`, `/featured`, `/ranking`, `/manga_list` 같은 nav 링크이고, `first_article_url` 은 제출 URL
자기 자신으로 잡혔다. `article_candidates.json`, `hydration.json`, `feed_candidates.json` 은 비어 있었다.

## URL/remap 확인

현재 URL 자체는 dead URL 이 아니다.

- `https://mangaplus.shueisha.co.jp/updates` → 200, SPA shell.
- robots.txt → `Disallow:` 비어 있음.
- soft-404 문구나 not-found shell 은 없음.

하지만 실제 목록 데이터는 HTML 이 아니라 브라우저가 호출하는 protobuf API 에 의존한다.

- HAR 핵심 호출: `https://jumpg-webapi.tokyo-cdn.com/api/web/web_homeV4?lang=eng&clang=eng`
- 같은 request headers(`Origin`, `Referer`, `SESSION-TOKEN`, UA) 로 replay 해도 200 + body `12 02 08 03`
  4바이트만 반환한다.
- `title_list/allV2`, `title_list/updated`, `title_list/all_v3`, `featuredV2`, `rankingV2`, `language` 도 같은
  4바이트 protobuf error 응답이다.
- probe click 이 잡은 `/www/custom_page?page_id=1120` 은 About Us 링크이며, click HAR 에서는 403 이다.

따라서 `/updates` 를 다른 board URL 로 remap 해서 살릴 근거가 없고, `list.url_template` 으로 쓸 수 있는
공개 HTML/JSON 목록 endpoint 도 확인되지 않았다.

## 판단

`httpx_html`/`playwright_html` config 는 nav/footer 만 긁게 되므로 같은 실패를 반복한다. `httpx_json` 도
protobuf decoding 과 API error 처리를 표현할 수 없어 맞지 않는다. 손어댑터로 protobuf schema 를 직접
디코딩하는 길은 검토했지만, 현재 API 응답 자체가 목록을 담지 않는 4바이트 error 이므로 adapter 를 써도
`posts_nonempty` 를 통과할 수 없다.

이 케이스는 soft-404 가 아니라 "SPA shell 은 접근 가능하지만 현재 환경에서 공개 목록 payload 를 얻지 못함"으로
거부한다. anti-bot/CAPTCHA/Cloudflare 화면은 아니어서 stealth 트랙으로도 즉시 풀 단서가 없다.

## Track B 검토

- **2a 인식기 — X.** 같은 플랫폼의 정상 API payload 를 얻지 못해 recognizer/config 발급으로 일반화할 수 없다.
- **2b article-url — X.** first article 이 잘못 잡힌 문제는 맞지만, 실제 article/update URL 후보가 없다.
- **2c/2d probe/prompt/engine — X.** probe 는 핵심 API 호출을 HAR 에 담았고, 문제는 후보 추출 누락보다 API 응답
  자체가 error payload 인 점이다. 이번 지시는 shared `probe/extract.py`, `scripts/register.py`, prompt, recognizer
  편집 금지이기도 하다.
- **2e 수동 config/adapter — X.** protobuf adapter 를 만들 수 있어도 현재 replay 응답이 목록을 포함하지 않아
  baseline 을 만들 수 없다.

일반화 안 되는 이유: 공개 목록 endpoint 가 확인된 패턴이 아니라 특정 site/API 접근 결과가 비어 있는 케이스다.

## 회귀 검증

- `preflight: b-hit — host_mangaplus-shuei_updates_28a3a423 [27ed350, 5665fa8]`
  - 기존 config 없음.
  - recognizer 매칭 없음.
  - 실패 이후 영향 영역 커밋 존재.
  - `python scripts/register.py --reuse-probe "https://mangaplus.shueisha.co.jp/updates"` → FAIL,
    `posts_nonempty: 0건`.
- URL/remap 확인
  - `/updates` → 200 shell, 글 row 없음.
  - `web_homeV4`, `title_list/allV2`, `title_list/updated`, `title_list/all_v3` replay → 200 + 4바이트 protobuf
    error body.
  - click-resolved About Us URL `/www/custom_page?page_id=1120` → 403.

## 자가 점검 (§6)

1. **자리**: none/rejected. 코드, schema, prompt, probe, recognizer 변경 없음.
2. **이전 케이스**: `posts_nonempty` 계열이지만 이번 원인은 nav-only selector 실패가 아니라 protobuf API empty/error.
3. **누구 깰까**: case 문서 1개만 추가. 기존 configs/engine 영향 0.
4. **검증**: `--reuse-probe` 실패 재현, URL/API replay, robots 확인.
5. **outcome=rejected**: config/adapter 로 baseline 을 만들 공개 목록 payload 가 없다.
6. **fixture**: 새 strategy/heuristic 없음.
7. **트랙 B 사유**: 위 §Track B 검토 참조.
