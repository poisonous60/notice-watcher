---
slug: host_ijcai-org_root_dd66bb09
url: https://ijcai.org/
status: 🚫 거부 (root landing/nav 링크 묶음 — chronological news/CFP board 아님)
outcome: rejected
date: 2026-05-21
fix_layer: none
failure_keys: [post_id_unique, nav_links, root_landing]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [ijcai, root, nav-only, not-a-board, rejected]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] post_id_unique: 중복 4건`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2d / §2g. 자동 config가 `future_conferences`, `past_conferences`, proceedings 같은 nav/root 링크를 글로 잡았다.
- 분기: 2e reject. root는 학회 landing/navigation hub이고 새 글 목록으로 보기 어렵다.
- preflight: b-hit — `register.py --reuse-probe`는 rc=0이었지만 결과가 `Conference Division`, `IJCAI-ECAI-26`, `Board of Trustees` 등 root 링크라 config를 제거했다.
- cross-check: `post_id_unique` 누적 9건, `track_b_trigger=true`. 기존 root/nav 게이트 범주로 기록하고 코드 변경은 보류했다.

## 결과

잘못 생성된 config는 제거했다. 실제 구독은 연도별 conference site나 news/announcement URL이 있으면 그 URL로 재시도해야 한다.

회귀 검증: config 없음. `probe_smoke --stage 3 --stage 5`로 기존 게이트 회귀만 확인.
