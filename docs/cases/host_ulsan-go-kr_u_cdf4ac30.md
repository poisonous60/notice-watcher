---
slug: host_ulsan-go-kr_u_cdf4ac30
url: https://www.ulsan.go.kr/u/rep/bbs/list.ulsan?bbsId=BBS_0000000000000001
status: "⏸ deferred — 원 board 빈 shell, 다른 bbsId 등록은 scope 오염"
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, empty_board, scope_pollution_risk]
config_strategy: none
---

제출된 `bbsId=BBS_0000000000000001` 은 울산소식 shell 만 렌더하고 데이터 row 0. codex 1차 시도가 같은 메뉴의 다른 `bbsId=BBS_0000000000000003` 으로 board 를 바꿔 config 등록했으나 — 사용자가 요청한 board scope 와 다른 board → 거부 + config revert.

- preflight: miss
- 조치: config 미작성 (scope 오염 차단). 진짜 사용자 요청 board (BBS_..._0001) 가 의도된 거면 catalog 수정 또는 사용자 재확인 후 처리.
- 일반화 안 되는 이유: scope 변경은 사용자 동의 사항. heuristic 으로 자동 매핑 X.
- 회귀 검증: 미해당.
