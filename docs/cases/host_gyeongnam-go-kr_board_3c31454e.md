---
slug: host_gyeongnam-go-kr_board_3c31454e
url: https://www.gyeongnam.go.kr/board/list.gyeong?boardId=BBS_0000060
status: "✅ 수동 config — menuCd/category 보정 후 경남 보도자료 10건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, missing_menuCd, board_shell]
config_strategy: httpx_html
---

제출 URL은 게시물 목록 shell만 내려준다. 공개 보도자료 목록은 `menuCd=DOM_000000135002001000&categoryCode1=A`를 포함해야 table row와 `dataSid` 상세 링크가 나온다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: 보정 URL 기준 table row config 추가
- 일반화 안 되는 이유: 경남 CMS의 `menuCd`는 사이트 메뉴 트리별 값이라 단일 config 보정으로 처리했다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
