---
slug: host_terms-naver-com_entry.naver_a297b3b0
url: https://terms.naver.com/entry.naver?docId=3579743&cid=59054&categoryId=59061
status: 🚫 거부 (단일 네이버 지식백과 항목 — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty, list_url_none, candidates_zero, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [naver-terms, single-entry-page, not-a-board, policy-reject]
---

## 무엇이 일어났나
사용자가 `https://terms.naver.com/entry.naver?docId=3579743&cid=59054&categoryId=59061` (네이버 지식백과 단일 항목 페이지) `/preview`. 자동 파이프 retry 실패 — `[FAIL] posts_nonempty: 0건`. last_config 는 `list.naver?cid=59054&categoryId={board}` 시도 (해당 cid/categoryId 의 카테고리 list URL 추측) + `#countControlByHeight > li.section_item` selector — list URL 은 맞을 가능성이지만 selector 가 잘못. 게다가 사용자가 *카테고리 list 알림* 을 원한 건지 *그 entry 알림* 을 원한 건지 명확하지 않음.

지식백과 카테고리(cid 59054 = 한국민족문화대백과사전 항목) 의 새 entry 추가는 빈도 매우 낮음 (사전 자체 갱신 주기 길음) — 폴링 의미 작음.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_terms-naver-com_entry.naver_a297b3b0.REJECTED.json` 마커.
- reason: "단일 네이버 지식백과 항목(entry.naver?docId=...) — 게시판 아님. 폴링 대상 X."
- note: "cid/categoryId list 페이지(list.naver?cid=...&categoryId=...)가 list 의도였다면 그것은 별 URL 로 등록. entry.naver?docId=... 자체는 자료 페이지."

`_save_rejected` 가 `terms.naver.com/entry.naver` host+path_prefix 학습.

## 후속 후보
- **트랙 B-2c (다른 case 와 공유)**: `is_article_page_url` 휴리스틱 + 사용자 안내. 같은 사이트의 `list.naver` URL 등록 의도였다면 LLM 가 retry feedback 으로 변환 시도하거나 사용자에게 명시 안내.
