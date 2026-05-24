---
slug: host_gg-go-kr_bbs_912082cf
url: https://www.gg.go.kr/bbs/board.do?bsIdx=464&menuId=1535
status: "⏸ deferred — 현재 직접 URL은 존재하지 않는 페이지 alert"
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, not_found_shell]
config_strategy: none
---

현재 dev box에서 제출 URL은 `존재하지 않는 페이지 입니다` alert 후 경기도청 main으로 이동한다. 검색 캐시에는 과거 `bsIdx=464` 상세 링크가 남아 있으나, 현행 목록 URL/board scope를 확정할 로컬 artifact가 없다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: config 작성 보류
- 일반화 안 되는 이유: 경기도 사이트의 현재 게시판 ID가 바뀐 것으로 보여, 임의의 다른 `bsIdx`를 등록하면 scope 오염이 된다.
- 회귀 검증: config 없음. N100 artifact 또는 현행 경기도 게시판 URL 확인 후 재개 필요.
