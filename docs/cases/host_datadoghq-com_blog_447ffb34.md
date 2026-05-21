---
slug: host_datadoghq-com_blog_447ffb34
url: https://www.datadoghq.com/blog/
status: ✅ 수동 config 등록 (httpx_html, baseline 6건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, blog-cards, nav-noise]
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. probe 상위 후보가 제품/솔루션 메뉴에 치우쳐 자동 config가 글 row를 못 잡았다.
- 분기: 2e 수동 config. recognizer 매칭 없음, blog card는 정적 HTML의 `article` 노드에 있다.
- preflight: `configs/<slug>.json` 없음, recognizer 없음. 실패 이후 영향 commit은 있었지만 이번 작업은 handcrafted config allow-list로 제한.
- 누적 cross-check: `posts_nonempty` count=34, `track_b_trigger=true`; deferred trigger도 존재.

## 해결

검색/tag 링크을 제외한 `/blog/<slug>/` 링크가 있는 `article`만 row로 채택했다. 첫 external feature card는 post_id가 없으므로 제외된다. 본문은 `section.article-content`를 사용한다.

검증:
- `validate_config`: OK
- `make_adapter`: list 5건 확인, 첫 글 `datadog-public-artifact-vulnerabilities-openvex`, body 40005자
- `register.py --config`: baseline 6건

## track-B 검토

root-cause는 nav/product 링크가 row 후보 상위에 올라온 점이다. posts_nonempty 누적은 track-B trigger 상태지만, 이번 allow-list가 probe row-detect 수정 금지라 일반화는 보류한다.

회귀 영향: 새 config 파일만 추가했다. 기존 config/engine 동작 영향 없음.
