---
slug: host_blog-unity-com_root_9fe1176b
url: https://blog.unity.com/
status: ✅ 수동 config 등록 (RSS 목록, baseline 30건; 본문 비움 허용)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, rss, client-rendered-article]
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. root HTML의 locale/blog card selector가 자동 config와 어긋났다.
- 분기: 2e 수동 config. recognizer 매칭 없음. probe에는 RSS 후보가 있고 RSS가 root HTML보다 안정적이다.
- preflight: `configs/<slug>.json` 없음, recognizer 없음. 실패 이후 영향 commit은 있었지만 이번 작업은 handcrafted config allow-list로 제한.
- 누적 cross-check: `posts_nonempty` count=34, `track_b_trigger=true`; deferred trigger도 존재.

## 해결

`https://blog.unity.com/rss`가 `https://unity.com/blog/rss`로 redirect되는 안정 RSS라 `item`을 row로 사용했다. Unity article page는 정적 HTML에서 본문이 client-rendered 상태라 `article.body_empty_acceptable: true`를 명시했다.

검증:
- `validate_config`: OK
- `make_adapter`: list 5건 확인, 첫 글 `unity-studio-collaboration-editor-export`, body 0자
- `register.py --config`: baseline 30건, body-empty warning 출력

## track-B 검토

probe가 RSS 후보를 이미 봤지만 자동 config가 RSS로 전환하지 못했다. RSS 후보 활용 개선은 track-B 후보이나 이번 allow-list가 probe/generate/prompt 수정 금지라 보류한다.

회귀 영향: 새 config 파일만 추가했다. 기존 config/engine 동작 영향 없음.
