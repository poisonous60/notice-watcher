---
slug: host_encyclopedia-us_content_fba2a7a9
url: https://encyclopedia.ushmm.org/content/en/article/the-great-depression
status: 🚫 거부 (USHMM Encyclopedia 단일 article page — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
failure_keys: [post_id_stable_shape, trending_article_links, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [ushmm, holocaust-encyclopedia, single-article-page, not-a-board, policy-reject]
requested_by: unknown
---

## 무엇이 일어났나
대상 URL 은 USHMM Holocaust Encyclopedia 의 단일 article page. 자동 생성 config 는 site header 의 trending article 링크를 목록처럼 잡았고, 긴 article slug 때문에 `post_id_stable_shape` 에서 실패했다.

header trending 링크는 사용자가 요청한 article 과 무관한 전역 추천 목록이다. 이를 등록하면 "The Great Depression article" 이 아니라 encyclopedia 홈의 추천 링크 변화를 감시하게 된다.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_encyclopedia-us_content_fba2a7a9.REJECTED.json` 마커.
- reason: "USHMM Encyclopedia 단일 article page — 게시판 아님. 폴링 대상 X."
- note: "전역 trending/header 링크를 게시글 목록으로 감시하지 않음. 최신 콘텐츠 목록/피드 URL이 있으면 그 URL로 등록 필요."

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** article URL fast-path 만들면 잘못된 게시판 승인.
- **2b (--article-url) — X.** 글 URL 교정 문제가 아님.
- **2c (probe heuristic) — 후보.** header/trending-only 목록을 article page로 거부하는 신호 가능. 사이트별 chrome/추천 링크 false positive 우려로 이번엔 코드 변경 안 함.
- **2d (probe artifact 수정) — X.** artifact 오작동 아님.

일반화 안 되는 이유: "trending links" 는 일부 사이트에서는 실제 최신 목록일 수 있어 단독 거부 신호로는 약함. slug REJECTED + learned blacklist 로 좁게 처리.

## 자가 점검 (§6)
1. **자리**: none (정책 거부).
2. **이전 케이스**: `host_terms-naver-com_entry.naver_a297b3b0`, `host_ko-wikipedia-or_wiki_3e20b56a`.
3. **누구 깰까**: 0 (tracked code/config 변경 없음).
4. **검증**: REJECTED marker 로 `is_registered=False` 경로.
5. **outcome=rejected_with_policy, fix_layer=none**.
6. **fixture**: skip (코드 변경 없음).
7. **트랙 B 0건 사유**: 위 §트랙 B.
