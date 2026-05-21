---
slug: host_sosp-org_root_06d54eed
url: https://sosp.org/
status: 🧩 수동 config — 정적 proceedings index selector 지정
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, row_selector_wrong]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, sosp, static-html, proceedings-index]
requested_by: batch
---

## 무엇이 일어났나

사용자 전달 기준 `https://sosp.org/` 는 httpx 로 접근 가능하지만 자동 config 가 글 row 를 못 잡아
`posts_nonempty=0` 이었다. 로컬에는 해당 `.FAILED.json` 과 `output/probe/.../list.html` 이 없어
probe 원문은 재인용하지 못했다.

직접 확인 결과 root HTML 은 구형 정적 페이지이며, proceedings 링크들이 `font > a[href]` 형태로 반복된다.
첫 행은 `http://www.sosp.org/2026` 이고 텍스트는 `Proceedings of the 32nd ACM Symposium... 2026,
Prague, Czechia.` 이다.

## 픽스

`configs/host_sosp-org_root_06d54eed.json` 생성. `row_selector` 는 `font:has(a[href*='sosp.org/'])`,
`post_id` 는 href 의 4자리 연도, `title` 은 row text, `url` 은 anchor href 로 추출한다.

## Track B 검토

- **2a 인식기 — X.** SOSP 단일 정적 index 다.
- **2b article-url — X.** 첫 글 URL은 정상적인 proceedings page 이고 문제는 row selector 다.
- **2c/2d probe/generate — 보류.** 구형 HTML proceedings index selector 일반화는 가능하지만 allow-list 밖이다.
- **2e 수동 config — O.** 정적 HTML selector 로 충분하다.

일반화 안 되는 이유: `<font>` 기반 구형 proceedings index 라 modern board heuristic 으로 일반화하기 애매하다.

## 회귀 검증

- `preflight: miss — host_sosp-org_root_06d54eed` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 5건, first post `2026`.
- 첫 글 `fetch_article()` body length 11226.

