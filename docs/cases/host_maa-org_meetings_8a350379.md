---
slug: host_maa-org_meetings_8a350379
url: https://www.maa.org/meetings
status: 🚫 거부 (입력 URL은 404, 발견된 feed는 전체 MAA 일반 글 feed라 meetings board와 불일치)
outcome: rejected
date: 2026-05-21
fix_layer: none
failure_keys: [target_not_found, posts_nonempty, unrelated_feed]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [maa, meetings, url-dead, unrelated-feed, rejected]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `TARGET_NOT_FOUND`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a / §2g. baseline root는 OK지만 입력 URL `/meetings`는 404다.
- 분기: 2e reject. `https://www.maa.org/feed`는 10건을 반환하지만 전체 MAA 일반 글 feed라 `/meetings` 의도와 맞지 않는다.
- preflight: b-hit — `register.py --reuse-probe`는 feed fallback으로 rc=0이었으나 `What does it mean to ask, “Who is math?”` 같은 일반 글이어서 config를 제거했다.
- cross-check: `posts_nonempty` 누적 67건, `track_b_trigger=true`. URL dead + unrelated feed라 코드 변경은 보류했다.

## 결과

config 없음. 올바른 meetings/section URL 또는 공식 meetings feed가 확인되면 별도 등록 대상이다.

회귀 검증: config 없음. `probe_smoke --stage 3 --stage 5`로 기존 게이트 회귀만 확인.
