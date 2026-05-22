---
slug: host_maven-apache-or_root_ed082572
url: https://maven.apache.org/
status: "거부 (Maven root는 최신 글 목록이 아니라 Maven 소개/문서 홈)"
outcome: rejected
date: 2026-05-22
fix_layer: none
failure_keys: [title_nonempty, posts_nonempty, content_not_board, stale_failed_queue]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [maven, apache, docs, root, content, rejected, stale-queue]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] title_nonempty: title 빈 글: ['current-event']`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2d / §2g. 자동 생성 config가 Maven root의 문서/내비게이션 링크를 글 목록처럼 잡았고, 이 URL 자체는 최신 글 목록이 아니다.
- 분기: preflight b-hit. 실패 시각 이후 `a9c5da5 feat(register): catalog 거부 + nav/연도-아카이브 오추출 게이트 (ADR 0011)` 가 영향 영역에 들어왔으므로 수동 config 대신 `register.py --reuse-probe` 로 회복 여부를 확인했다.
- preflight: b-hit — `host_maven-apache-or_root_ed082572` [`a9c5da5`]. recognizer/config는 없었고, 실패 이후 register/게이트 변경이 있었다.
- cross-check: `title_nonempty` 7건, `posts_nonempty` 92건으로 둘 다 track-B trigger=true. 다만 이번 slug는 새 휴리스틱/recognizer가 필요한 게시판이 아니라, 최신 분류기에서 content로 정상 거부된 stale FAILED 큐다.
- deferred cross-check: deferred trigger는 여러 건 존재하지만, Maven root에 직접 적용할 Track B는 없다. 이 페이지는 static docs/product home이며 board URL 회복 후보가 아니다.

## 결과

`python scripts/register.py --reuse-probe "https://maven.apache.org/"` 결과:

```text
[register] 🔴 모든 게이트 통과했으나 LLM 분류기가 content(비-게시판)로 판단 — 등록 거부 rc=3 (conf=0.95, Maven 자체를 소개하는 단일 문서형 소개 페이지로, 최신 글 목록이 아니라 제품 설명과 안내 본문이 중심이다)
```

`output/poll_state/host_maven-apache-or_root_ed082572.REJECTED.json` 이 생성됐고 기존 FAILED 마커와 triage queue 항목은 정리됐다. config 없음. 올바른 등록 대상은 Maven root가 아니라 실제 release/news/feed 같은 목록 URL이 확인될 때 별도 slug로 처리해야 한다.

## 회귀 검증

- 영향 config 없음. `make_adapter` 손 실행은 해당 없음.
- `python scripts/probe_smoke.py --stage 3 --stage 5` -> PASS 1126, FAIL 0, WARN 0, SKIP 0. Stage 3 configs 195/195 OK, stage 5 heuristic units 85 files / 930 cases / 0 FAIL / coverage 37/37.
