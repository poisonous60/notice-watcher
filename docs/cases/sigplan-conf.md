---
slug: host_popl26-sigplan-_root_cc2798a1
url: https://popl26.sigplan.org/
status: ✅ 해결 (SIGPLAN/researchr Conf recognizer 추가)
outcome: handcrafted
date: 2026-05-21
failure_keys: [post_id_unique]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/sigplan_conf.py]
tags: [sigplan, researchr, conference, recognizer, post-id]
requested_by: batch
---

## 무엇이 일어났나

academic batch에서 `https://pldi26.sigplan.org/`는 rc=0으로 등록됐지만,
같은 SIGPLAN/researchr Conf 계열인 `https://popl26.sigplan.org/`는 자동 생성 config가
`[FAIL] post_id_unique`로 실패했다.

사용자 제공 probe 요약에 따르면 POPL 실패는 `post_id_unique` 중복 1건이었다. live HTML 확인 결과
POPL/PLDI 모두 home page의 featured paper carousel에 `a.highlight-carousel-item.navigate` 행이 있고,
각 링크는 `/details/.../<id>/...` 형태의 안정 숫자 ID를 가진다.

## 원인

자동 생성 config가 carousel 주변 컨테이너를 넓게 잡으면 같은 detail 링크가 중복 row로 추출될 수 있다.
반대로 행을 `a.highlight-carousel-item.navigate[href*='/details/']` anchor 자체로 좁히면 POPL은 2건,
PLDI는 3건이 추출되고 `/details/.../<id>/` 숫자 segment가 중복 없이 `post_id`가 된다.

## 픽스

`engine/recognizers/sigplan_conf.py`를 추가했다.

- `NAME = "sigplan_conf"`
- root conference URL만 매칭: `https://<sub>.sigplan.org/`
- `site`는 실제 host, `board`는 `home`
- `row_selector`: `a.highlight-carousel-item.navigate[href*='/details/']`
- `post_id`: `href`의 `/details/[^/]+/(\d+)/`
- `title`: row 안의 `h5`
- `url`: row anchor `href`
- `author`: `h6 i`, fallback으로 profile image `alt`
- `article.content`: detail page의 `#content`

`.acm.org` 계열(`chi2026.acm.org` 등)은 이 recognizer가 매칭하지 않는다.

## Track B 검토

- **2a (recognizer)**: O. SIGPLAN conference subdomain들이 같은 researchr Conf DOM과 URL 패턴을 공유한다.
- **2b (`--article-url`)**: X. 첫 글 URL 자체는 정상이고, 실패 원인은 row 범위/ID 추출이다.
- **2c/2d (probe/generator 개선)**: 보류. `post_id_unique` 누적은 trigger=true지만 이번 요청의 allow-list가 F-layer recognizer와 case/index로 제한되어 있다.
- **2e (수동 config)**: X. 단일 config보다 플랫폼 recognizer가 같은 SIGPLAN conference root URL을 더 잘 커버한다.

## 회귀 검증

- `recognize('https://popl26.sigplan.org/')` → `site='popl26.sigplan.org'`, `board='home'`, `_recognized_platform='sigplan_conf'`
- `recognize('https://pldi26.sigplan.org/')` → `site='pldi26.sigplan.org'`, `board='home'`, `_recognized_platform='sigplan_conf'`
- `recognize('https://chi2026.acm.org/')` → `None`
- POPL `make_adapter(fetch_list page_size=100)` → list 2건, duplicate post_id 0건
- POPL `validate_built_config(fetch_articles=1)` → `ok=True`, article body 41472자
- PLDI `make_adapter(fetch_list page_size=100)` → list 3건, duplicate post_id 0건
- PLDI `validate_built_config(fetch_articles=1)` → `ok=True`, article body 37920자

## 자가 점검 (§6)

1. **자리**: F-layer recognizer. probe/generator 수정 없이 URL path-match로 known platform config를 발급한다.
2. **이전 케이스**: `post_id_unique` 누적 8건, `track_b_trigger=true`. 이번 케이스는 carousel 중복 일반론보다 SIGPLAN/researchr Conf의 안정 URL 패턴이 더 직접적인 해결책이다.
3. **누구 깰까**: root `*.sigplan.org/`만 매칭하므로 `.acm.org`와 detail page는 제외된다. 기존 recognizer와 host 충돌 없음.
4. **검증**: 위 회귀 검증과 `probe_smoke --stage 3 --stage 5` 참조.
5. **outcome=handcrafted, fix_layer=F**.
6. **fixture**: 새 fixture 없음. live POPL/PLDI fetch로 selector와 ID 중복 여부를 검증했다.
7. **트랙 B 보류 사유**: allow-list 밖인 `probe/`, `generate/`, prompt 수정 없이도 플랫폼 recognizer로 같은 SIGPLAN Conf root URL을 처리할 수 있다.
