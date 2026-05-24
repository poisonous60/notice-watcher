---
slug: host_kiep-go-kr_gallery.es_103af3af
url: https://www.kiep.go.kr/gallery.es?mid=a10501000000&bid=0001
status: "✅ 수동 config — KIEP gallery.es 보고서/공지 목록 10건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [gate_reject, false_reject, board_shape_check]
config_strategy: httpx_html
---

KIEP `gallery.es`는 classifier가 content로 본 false-reject였지만 실제 페이지에는 `div.board_list li` 반복 행과 `act=view&list_no=` 상세 링크가 있다.

- preflight: miss — 로컬 FAILED/probe artifact 없음, N100 pull 금지로 직접 현 페이지 확인
- 조치: `configs/host_kiep-go-kr_gallery.es_103af3af.json` 추가
- 일반화 안 되는 이유: classifier prompt/engine 수정은 이번 allow-list 밖이라 사이트 config만 기록한다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
