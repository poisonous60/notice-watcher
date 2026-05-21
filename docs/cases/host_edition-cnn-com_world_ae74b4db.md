---
slug: host_edition-cnn-com_world_ae74b4db
url: https://edition.cnn.com/world
status: ✅ 자동 등록 (validation cap 64→200 완화 후 자동 통과 — playwright_html, 30건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: E
failure_keys: [post_id_stable_shape, posts_nonempty, matches_probe_first_article]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: [generate/validate.py, scripts/poll.py, tests/validate/test_post_id_stable_shape.py]
tags: [cnn, url-slug-as-id, stable-id-shape-cap, news-media, validation-relaxation, robots-disallow-warn]
requested_by: poi23619
---

## 무엇이 일어났나

`/preview https://edition.cnn.com/world` (poi23619, 2026-05-19 02:18 UTC). 3 attempt 모두 실패 → FAILED.json.

| attempt | strategy | row_selector | fail |
|---|---|---|---|
| 1 | httpx_html | `li.card[data-link-type='article']` | `posts_nonempty: 0건` |
| 2 | playwright_html | `li.card[data-open-link]` | `post_id_stable_shape: 안정적 ID 모양 아님` |
| 3 | httpx_html | `ul.container__field-links.container_grid-4__field-links > li.card...` (긴 selector) | `post_id_stable_shape` (post_ids 60~130자, body 75539자 — 추출 자체는 성공) |

## 왜

attempt 3 가 결정적: post_id 추출 자체는 정상이고 본문도 75539자 잘 받았는데, validation 의 `_STABLE_ID_RE = r"^[\w\-./:%]{1,64}$"` 가 130자 슬러그를 거부했다. CNN URL 패턴 = `/<YYYY>/<MM>/<DD>/<section>(/<subsection>)?/<title-slug>` — title-slug 가 단독으로 80~120자.

샘플 post_id:
- `2026/05/18/world/video/north-korean-womens-soccer-team-arrives-in-south-korea-for-the-first-time-in-over-7-years-ripley-hnk-digvid` (130자)
- `2026/05/18/china/xi-trump-trade-agreements-china-visit-intl-hnk` (60자 — 통과)

64자 한도의 원래 의도 = "'title with spaces' 같은 실수 차단" (주석 명시). 하지만 shape regex `[\w\-./:%]` 가 *이미* 공백을 배제해 — 길이 cap 은 redundant guard. 주요 뉴스 미디어 (CNN/NYT/WaPo/Reuters/Guardian) 는 모두 date+title-slug URL 패턴 → 100~150자 정상.

`scripts/remote.py:49` 의 `_POST_ID_RE` 는 이미 cap=128 — 같은 의도의 룰끼리 불일치 (`validate.py`·`poll.py` = 64, `remote.py` = 128).

## 픽스 (fix_layer: E — validation 룰 완화)

`_STABLE_ID_RE` cap 64 → 200:

- `generate/validate.py:22` — `r"^[\w\-./:%]{1,200}$"` + 주석에 "메이저 뉴스미디어의 date+title-slug URL path 패턴 수용" 명시.
- `scripts/poll.py:46` — 동기. runtime warn 룰도 같이 완화.
- `scripts/remote.py:49` (이미 128) — 향후 200 동기 후보 (별 commit, validation 통과만 우선).

shape regex 자체는 그대로 (공백·제어문자 거부). 200 cap 은 관측 최대값(130자) 의 1.5x 여유.

## 트랙 A (사용자) / 트랙 B (미래)

같은 fix. cap 완화 후 `register.py --reuse-probe` → **attempt 2 PASS (30건)** → CNN `/world` 자동 등록. 수동 config X.

미래 영향: 같은 패턴의 모든 메이저 뉴스 미디어 root/section URL — NYT/WaPo/Guardian/BBC/Reuters 의 date+slug 경로 — 같은 cap 룰에 막혀온 가능성. 본 fix 가 향후 사용자 등록 비용 0.

## 트랙 B 후보 점검 (한 줄씩)

- 2a 인식기 — X — CNN 단일 호스트, 플랫폼 X. 패턴 추가 가치 낮음.
- 2b `--article-url` — X — probe first_article 자체는 합리적 (`first_article_url='https://.../ebola-outbreak-drc-linkedto-100-deaths-digivid-intldsk'`), 신호 멀쩡.
- 2c probe 휴리스틱 — X — probe digest 다 멀쩡함. diagnosis verdict `정적 HTTP로 충분` 정답. probe 가 빠뜨린 신호 X.
- 2d probe artifact — X — 산출물 완전.
- **(E) validation 룰** — O — 이 fix 가 채택.

## robots.txt 노트

CNN robots.txt = `User-agent: * / Disallow: /` (사이트 전체). 현재 정책 (`docs/config 자동생성 실패 케이스.md:29`) = warn-only, register 진행. 본 등록은 일 1회 폴링 + 1페이지 + polite_sleep 정책 (`docs/크롤링 지침.md`) 하에서 부담 미미하다고 판단. 추후 robots-global-disallow gate 박는다면 본 등록도 회수 대상 — 별 작업.

## 검증

- `python tests/validate/test_post_id_stable_shape.py` — 12 fixture (URL-slug 130자 accept, 200자 accept, 201자 reject, 공백 reject, 빈 문자열 reject, `?&` 등 제어문자 reject) 모두 PASS.
- `python scripts/probe_smoke.py --stage 3 --stage 5` — 40 configs OK / 38 파일 357 케이스 0 FAIL.
- `python scripts/register.py --reuse-probe "https://edition.cnn.com/world"` — attempt 2 PASS, 30건 baseline.

### 회귀 영향 (다른 configs 안전성)

cap 완화 = *strict superset* (200 ≥ 64). 64 cap 으로 통과한 모든 기존 등록 사이트는 자동으로 200 cap 도 통과 — 거부 방향 변화 X, 새 거부 0개.

확증: 40 configs (stage 3) + 모든 poll_state baseline post_ids — 본 변경 전에 이미 ≤64 였으므로 ≤200. 새 변경 후 stage 3 (configs validate + make_adapter) 40/40 OK 도 동일 사실 확인 (이전 baseline post_ids 가 200 한도 검사로 옮겨갔다고 가정).

리스크 면: 200자에 가까운 길이의 `[\w\-./:%]` 문자열을 `post_id` 로 *실수로* 박는 경우 — title이 한국어 단일 단어 chained 또는 모든 공백을 `-` 로 변환한 매우 긴 slug. shape regex 가 *언어 검출* 까진 안 함. 다만 그런 case 는 64 cap 도 못 잡았을 가능성 (`[\w]` = Unicode word char) — cap 200 도 같은 등급. 본 fix 가 *추가로* 깨는 시나리오 없음.

## 관련

- [[host_nationalgeograp_root_2be4a852]] — vocab_candidates 의 `unstable_post_id` (slug-based post_id stable_shape 완화 검토) — 본 fix 로 해소. NatGeo root 자체는 별도 root_marketing_homepage 게이트로 거부 상태.
- [[infra_root_marketing_homepage_gate_2026-05-19]] — root marketing landing gate (path='/' 만 잡음). CNN `/world` 는 path='/world' 라 안 잡힘 — 본 case 의 자매 게이트 X.
