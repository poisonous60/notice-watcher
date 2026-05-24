---
slug: host_kita-net_asocGuidance_6a214a7a
url: https://www.kita.net/asocGuidance/nesDta/nesDtaList.do
status: "✅ 수동 config — KITA pressData redirect board 10건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, redirect_board_url, javascript_detail]
config_strategy: httpx_html
---

제출 URL은 KITA 보도자료 목록으로 리다이렉트된다. 행은 `.board-list li`, 상세는 `goDetailPage(no)`에서 `/board/pressData/pressDataDetail.do?no=<id>`로 구성할 수 있다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: redirect 후 pressData board 기준 config 추가
- 일반화 안 되는 이유: KITA의 `goDetailPage` form submit 규칙은 사이트 전용이다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
