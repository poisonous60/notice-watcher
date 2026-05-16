---
slug: host_ko-wikipedia-or_wiki_3e20b56a
url: https://ko.wikipedia.org/wiki/%EC%99%95%EC%88%98%EC%9D%B8
status: 🚫 거부 (단일 위키 항목 페이지 — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty, list_url_none, candidates_zero, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [wikipedia, single-article-page, not-a-board, policy-reject]
---

## 무엇이 일어났나
사용자가 `https://ko.wikipedia.org/wiki/왕수인` (위키피디아 단일 항목 페이지) `/preview`. 자동 파이프 retry 실패 — `[FAIL] posts_nonempty: 0건`. `list_url=None`, `candidates=0`, `first_article='/wiki/1472년'` (본문 안 위키링크). last_config 가 추측한 `wiki/특수:최근바뀜` + `ul.mw-changeslist-list > li.mw-changeslist-line` — 위키 최근바뀜은 의미 있는 selector 지만 사용자가 원한 것 (= 그 항목의 알림) 과 무관. 위키피디아는 일반화로 폴링할 board 가 아니다.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_ko-wikipedia-or_wiki_3e20b56a.REJECTED.json` 마커.
- reason: "단일 위키피디아 항목 페이지(/wiki/<title>) — 게시판 아님. 폴링 대상 X."
- note: "폴링이 의미 있으려면 게시판/카테고리 인덱스 URL 필요. 그 페이지 변경 이력 알림을 원했다면 wikipedia 의 watchlist/RSS 별도 — 자동 파이프 범위 밖."

`_save_rejected` 가 `output/learned_blacklist.json` 에 host+path_prefix 패턴 자동 학습 (`ko.wikipedia.org/wiki/*` 거부). 다른 사용자가 같은 패턴 `/preview` 하면 봇 url_gate 가 즉시 차단.

## 일반화 안 함 이유
1건만으론 `wiki.*/*` 또는 *mediawiki 일반* 차단 룰 만들기 위험. mediawiki 사이트 중 community 게시판 (Talk:, namespace) 폴링 needs 가 있을 수 있음. host+path_prefix 학습된 룰은 `ko.wikipedia.org/wiki/` 만 거부 — 충분히 좁음.

## 후속 후보
- **트랙 B-2c (다른 case 와 공유)**: probe digest 에 `is_article_page_url` 휴리스틱 — wikipedia article URL 도 잡힘 → preflight 거부 + 사용자에게 "특정 카테고리·포털 URL 줘" 안내. 1회 LLM 호출도 안 가도록 사전 차단.
