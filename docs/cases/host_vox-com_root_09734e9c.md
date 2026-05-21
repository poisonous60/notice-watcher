---
slug: host_vox-com_root_09734e9c
url: https://www.vox.com/
status: ✅ 수동 config 등록 (httpx_html, baseline 7건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, responsive-duplicates]
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 자동 config가 hashed content-card root를 잡으며 responsive duplicate와 selector drift에 걸렸다.
- 분기: 2e 수동 config. recognizer 매칭 없음, root HTML에 중복 없는 numbered list가 있다.
- preflight: `configs/<slug>.json` 없음, recognizer 없음. 실패 이후 영향 commit은 있었지만 이번 작업은 handcrafted config allow-list로 제한.
- 누적 cross-check: `posts_nonempty` count=34, `track_b_trigger=true`; deferred trigger도 존재.

## 해결

중복 content-card 대신 `main ol li`의 static ranked list를 row로 사용했다. `href`의 숫자 segment를 `post_id`로 쓰고 본문은 `main article`을 우선 사용한다.

검증:
- `validate_config`: OK
- `make_adapter`: list 5건 확인, 첫 글 `489067`, body 47564자
- `register.py --config`: baseline 7건

## track-B 검토

responsive duplicate card와 hydration 후보가 같이 있었지만, 이번 allow-list상 dedup/row-detect 개선은 수행하지 않았다. 같은 유형이 누적되어 있어 별도 track-B 작업으로 처리해야 한다.

회귀 영향: 새 config 파일만 추가했다. 기존 config/engine 동작 영향 없음.
