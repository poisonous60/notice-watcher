---
slug: host_bucheon-go-kr_site_34226c83
url: https://www.bucheon.go.kr/site/program/board/basicboard/list?boardtypeid=26736
status: "✅ 수동 config — menuid 보정 후 부천 새소식 20건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, missing_menuid, auth_redirect]
config_strategy: httpx_html
---

제출 URL은 `menuid`가 없어 권한 오류 페이지로 이동한다. 같은 `boardtypeid=26736`에 `menuid=148002001001&pagesize=20`을 붙이면 공개 새소식 목록이 열린다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: 보정 URL 기준 table row config 추가
- 일반화 안 되는 이유: 부천 CMS의 boardtypeid/menuid 결합은 사이트별 메뉴 매핑이다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
