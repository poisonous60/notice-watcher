---
slug: host_daegu-go-kr_icms_60f0b219
url: https://www.daegu.go.kr/icms/bbs/selectBoardList.do?bbsId=BBS_0000004
status: "⏸ deferred — 현재 직접 URL은 게시판 설정 없음으로만 응답"
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, board_config_missing]
config_strategy: none
---

현재 dev box에서 제출 URL을 열면 `게시판설정 정보를 확인할 수 없습니다` alert shell만 반환되고 `/`로 이동한다. 대구 CMS는 `index.do?menu_id=...&menu_link=...` 래퍼가 필요한 유형으로 보이나, 이번 로컬 환경에는 원 probe artifact가 없고 N100 pull도 금지되어 실제 메뉴 ID를 확정할 수 없었다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: config 작성 보류
- 일반화 안 되는 이유: 메뉴 ID 추정 없이 임의 대구 게시판으로 대체하면 사용자가 요청한 board scope가 바뀐다.
- 회귀 검증: config 없음. N100 artifact의 `list.html/list_candidates.json` 또는 실제 menu_id 확인 후 재개 필요.
