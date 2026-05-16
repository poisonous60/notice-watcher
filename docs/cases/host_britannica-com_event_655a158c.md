---
slug: host_britannica-com_event_655a158c
url: https://www.britannica.com/event/Great-Depression
status: 🚫 거부 (Britannica 단일 article page — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
failure_keys: [post_id_stable_shape, related_question_links, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [britannica, single-article-page, related-links, not-a-board, policy-reject]
requested_by: unknown
---

## 무엇이 일어났나
대상 URL 은 Britannica 의 Great Depression 단일 article page. 자동 생성 config 는 "Related Questions" 링크 5건을 목록처럼 잡았고, 긴 question slug 때문에 `post_id_stable_shape` 에서 실패했다.

하지만 root cause 는 validator 가 아니라 입력 URL 성격이다. 사용자가 준 페이지는 새 글이 쌓이는 게시판/목록이 아니라 고정 encyclopedia article 이고, related question 링크를 polling 대상으로 삼으면 "article page 안의 참고 링크 목록"을 새 공지처럼 감시하게 된다.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_britannica-com_event_655a158c.REJECTED.json` 마커.
- reason: "Britannica 단일 article page — 게시판 아님. 폴링 대상 X."
- note: "관련 질문/본문 링크를 게시글 목록으로 감시하지 않음. 폴링이 의미 있으려면 최신 글/목록/피드 URL 필요."

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** Britannica article URL 을 게시판으로 fast-path 처리하면 false positive.
- **2b (--article-url) — X.** 글 URL 교정 문제가 아니라 입력이 단일 article.
- **2c (probe heuristic) — 후보.** `is_article_page_url` / related-links-only 패턴을 preflight 거부 신호로 승격 가능. 이번엔 기존 learned REJECTED 패턴으로 충분해 코드 변경 안 함.
- **2d (probe artifact 수정) — X.** artifact 는 관련 링크를 정상 관찰했다.

일반화 안 되는 이유: article-page 거부 휴리스틱은 Wikipedia/terms/encyclopedia 계열까지 넓게 닿아 false positive risk 있음. 지금은 slug REJECTED + learned blacklist 로 좁게 차단.

## 자가 점검 (§6)
1. **자리**: none (정책 거부).
2. **이전 케이스**: `host_ko-wikipedia-or_wiki_3e20b56a`, `host_terms-naver-com_entry.naver_a297b3b0` 와 같은 single-article-page 거부.
3. **누구 깰까**: 0 (tracked code/config 변경 없음).
4. **검증**: REJECTED marker 로 `is_registered=False` 경로.
5. **outcome=rejected_with_policy, fix_layer=none**.
6. **fixture**: skip (코드 변경 없음).
7. **트랙 B 0건 사유**: 위 §트랙 B.
