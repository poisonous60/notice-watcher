---
slug: host_ulsan-go-kr_u_cdf4ac30
url: https://www.ulsan.go.kr/u/rep/bbs/list.ulsan?bbsId=BBS_0000000000000001
status: "✅ 수동 config — 같은 메뉴의 실제 울산소식 bbsId=...0003 목록 10건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, empty_board_id, missing_mId]
config_strategy: httpx_html
---

제출된 `bbsId=BBS_0000000000000001`은 울산소식 shell을 렌더하지만 데이터 row가 없다. 같은 메뉴에서 공개되는 실제 울산소식 목록은 `bbsId=BBS_0000000000000003&mId=001004001001000000`이며 `dataId` 상세 링크가 안정적으로 나온다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: 실제 울산소식 board ID 기준 config 추가
- 일반화 안 되는 이유: board ID 보정은 사이트별 메뉴/게시판 매핑이다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
