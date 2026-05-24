---
slug: host_kbiz-or-kr_ko_9f121943
url: https://www.kbiz.or.kr/ko/contents/contents/contents.do?mnSeq=207
status: "✅ 수동 config — KBIZ mnSeq=207 보도자료 board URL로 12건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, menu_landing_as_list, javascript_detail]
config_strategy: playwright_html
---

제출 URL은 메뉴 landing인 `contents.do`이고 실제 반복 행은 같은 `mnSeq=207`의 `/ko/contents/bbs/list.do`에 있다. 행은 `.board-list li`, 상세는 `goView(seq)`에서 `view.do?seq=<id>&mnSeq=207`로 구성된다. 정적 응답은 중복 `<html>` 때문에 lxml 파서가 보드 영역을 놓쳐 `playwright_html`로 렌더 DOM을 사용했다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: KBIZ board URL 기준 config 추가
- 일반화 안 되는 이유: `mnSeq` landing에서 bbs/list로 이동하는 것은 KBIZ 전용 메뉴 규칙이다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
