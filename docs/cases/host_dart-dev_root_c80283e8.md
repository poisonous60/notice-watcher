---
slug: host_dart-dev_root_c80283e8
url: https://dart.dev/
status: "거부 (Dart 문서 홈은 최신 글 목록이 아니라 언어/제품 소개 페이지)"
outcome: rejected
date: 2026-05-22
fix_layer: none
failure_keys: [posts_nonempty, content_not_board, stale_failed_queue]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [dart, docs, root, content, rejected, stale-queue]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a / §2g. 정적 HTML 접근은 되지만 root 페이지의 반복 링크는 `#docs-*` 사이드바 문서 nav이고, 최신 글 목록이 아니다.
- 분기: preflight b-hit. 실패 시각 이후 `a9c5da5 feat(register): catalog 거부 + nav/연도-아카이브 오추출 게이트 (ADR 0011)` 가 영향 영역에 들어왔으므로 수동 config 대신 `register.py --reuse-probe` 로 회복 여부를 확인했다.
- preflight: b-hit — `host_dart-dev_root_c80283e8`. recognizer/config는 없었고, 실패 이후 register/게이트 변경이 있었다.
- cross-check: 사용자 지시로 `cases_index.py`/INDEX/DB 작업은 생략했다.

## 결과

`python scripts/register.py --reuse-probe "https://dart.dev/"` 결과:

```text
[register] 모든 게이트 통과했으나 LLM 분류기가 content(비-게시판)로 판단 - 등록 거부 rc=3 (conf=0.78, 단일 주제인 Dart 언어 소개/설명 페이지로, 최신 글 목록이 아니라 제품·기술 소개 본문에 해당한다)
```

`output/poll_state/host_dart-dev_root_c80283e8.REJECTED.json` 이 생성됐고 기존 FAILED 마커는 정리됐다. config 없음. 올바른 등록 대상은 Dart 문서 root가 아니라 실제 changelog/blog/feed 같은 목록 URL이 확인될 때 별도 slug로 처리해야 한다.

## 회귀 검증

- 영향 config 없음. `make_adapter` 손 실행은 해당 없음.
- `python scripts/probe_smoke.py --stage 3 --stage 5` -> PASS 1122, FAIL 0, WARN 0, SKIP 0. Stage 3 configs 191/191 OK, stage 5 heuristic units 85 files / 930 cases / 0 FAIL / coverage 37/37.
