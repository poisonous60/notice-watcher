---
slug: host_apa-org_science_e0556b0f
url: https://www.apa.org/science/about/psa/
status: 🚫 거부 (입력 URL이 APA PSA 목록이 아니라 404/사이트 안내 링크만 제공 — poll 대상 게시판 아님)
outcome: rejected
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, matches_probe_first_article, nav_only_same_host]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [apa, academic, not-a-board, nav-only, rejected]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `JS 실행 필요 (Cloudflare 등)`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a / §2g. 자동 생성이 `https://www.apa.org` 계열 사이트 링크를 첫 글로 잡았다.
- 분기: 2e reject. 현재 URL은 `traffic.har`에서 404였고, `list.html`에는 `APA.org`, `APA Style`, `APA Services` 같은 사이트 안내 링크만 있었다.
- preflight: b-hit — 실패 뒤 recognizer/probe/generate 커밋이 있어 `register.py --reuse-probe`를 실행했지만, rc=0 결과가 APA 계열 사이트 메뉴 5건이라 의도와 불일치했다.

## 결과

잘못 생성된 config는 제거했다. 이 URL은 구독 대상 board로 보지 않는다.

트랙 B 검토: `posts_nonempty`와 `nav_only_same_host`는 누적 트리거가 이미 true지만, 이번 케이스는 기존 nav-only/root 게이트가 LLM veto로 취소된 false-cancel 성격이다. 분류기 개선 후보로만 기록하고 코드 변경은 보류했다.

회귀 검증: config 없음. `probe_smoke --stage 3 --stage 5`로 기존 게이트 회귀만 확인.
