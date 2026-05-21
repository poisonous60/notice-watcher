---
slug: host_grafana-com_blog_d681aff2
url: https://grafana.com/blog/
status: ✅ 수동 config 등록 (httpx_html, baseline 30건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, blog-cards]
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 자동 config가 잘못된 section root를 반복해 목록이 0건이었다.
- 분기: 2e 수동 config. recognizer 매칭 없음, list.html에 실제 글 카드가 정적으로 존재.
- preflight: `configs/<slug>.json` 없음, recognizer 없음. 실패 이후 영향 commit은 있었지만 이번 작업은 handcrafted config allow-list로 제한.
- 누적 cross-check: `posts_nonempty` count=34, `track_b_trigger=true`; deferred trigger도 존재.

## 해결

`article:has(a[href^='/blog/'])` 기반으로 실제 blog card를 잡고, 빈 이미지 링크 대신 텍스트가 있는 첫 blog link를 title로 골랐다. 본문은 `div.rich-text`를 우선 사용한다.

검증:
- `validate_config`: OK
- `make_adapter`: list 5건 확인, 첫 글 `grafana-labs-security-update-latest-on-tanstack-npm-supply-chain-ransomware-incident`, body 8884자
- `register.py --config`: baseline 30건

## track-B 검토

probe 후보에는 실제 row(`ul.space-y-10 > li`)가 있었지만 자동 config가 root를 잘못 선택했다. 동일 패턴 재발은 가능하나 이번 HARD-STOP에서 prompt/probe 개선 파일 수정이 금지되어 case에만 남긴다.

회귀 영향: 새 config 파일만 추가했다. 기존 config/engine 동작 영향 없음.
