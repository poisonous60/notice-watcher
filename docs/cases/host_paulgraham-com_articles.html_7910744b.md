---
slug: host_paulgraham-com_articles.html_7910744b
url: https://paulgraham.com/articles.html
status: ✅ 수동 config 등록 (httpx_html, baseline 30건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, old-table-layout]
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 정적 HTML에는 글 링크가 있으나 자동 config가 table/font 중간 노드를 row로 잡아 0건이 됐다.
- 분기: 2e 수동 config. recognizer 매칭 없음, 단일 사이트의 오래된 HTML 구조라 일반 플랫폼화 대상은 아님.
- preflight: `configs/<slug>.json` 없음, recognizer 없음. 실패 이후 영향 commit은 있었지만 이번 작업은 handcrafted config allow-list로 제한.
- 누적 cross-check: `posts_nonempty` count=34, `track_b_trigger=true`; deferred trigger도 존재.

## 해결

`font a[href$='.html']` 자체를 row로 보고 `href`에서 `post_id`와 `url`을 추출했다. 본문은 각 글의 정적 HTML `body`를 사용한다.

검증:
- `validate_config`: OK
- `make_adapter`: list 5건 확인, 첫 글 `greatwork`, body 75535자
- `register.py --config`: baseline 30건

## track-B 검토

일반화 후보는 있으나 이번 allow-list가 `probe/`, `engine/`, `scripts/` 수정을 금지한다. 이 케이스 자체는 paulgraham 고유의 old table/font index라 probe row-detect 개선보다 수동 config가 적절하다.

회귀 영향: 새 config 파일만 추가했다. 기존 config/engine 동작 영향 없음.
