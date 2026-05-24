---
slug: host_sba-seoul-kr_Pages_1691c5a8
url: https://www.sba.seoul.kr/Pages/ContentsMenu/Company_Support.aspx
status: "✅ 수동 config — SBA 기업지원 card_box 목록 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, rendered_cards, javascript_detail]
config_strategy: playwright_html
---

SBA 기업지원 페이지는 카드형 목록을 `div.card_box`로 렌더하고 상세 링크는 `contentsDetail(RID)` javascript 함수에 들어 있다. 상세 본문은 동적/요약 영역이 섞여 있어 목록 추출을 주 신호로 두고 body empty를 허용했다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: `playwright_html` + `div.card_box` config 추가
- 일반화 안 되는 이유: RID 기반 `Company_Support_Detail.aspx` 구성은 SBA 전용이다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
