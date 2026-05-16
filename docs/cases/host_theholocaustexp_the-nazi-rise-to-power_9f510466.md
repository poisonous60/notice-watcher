---
slug: host_theholocaustexp_the-nazi-rise-to-power_9f510466
url: https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/the-role-of-economic-instability/
status: 🚫 거부 (The Holocaust Explained 단일 article/subtopic page — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
failure_keys: [article_body_len, embedded_subtopics, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [theholocaustexplained, single-article-page, embedded-subtopics, not-a-board, policy-reject]
requested_by: unknown
---

## 무엇이 일어났나
대상 URL 은 The Holocaust Explained 의 단일 article/subtopic page. 자동 생성 config 는 상위 topic page의 `article.subtopic` 블록 8건을 row 로 잡았지만, `a.topic-link` selector 가 없어 `post.url=None` 이 되었고 `article_body_len` 에서 실패했다.

subtopic 블록들은 한 topic page 안의 고정 학습 콘텐츠 섹션이다. fragment anchor 로 억지 등록하면 모든 fetch 가 같은 HTML 문서를 다시 가져오며, 개별 subtopic change/new-post polling 이 되지 않는다.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_theholocaustexp_the-nazi-rise-to-power_9f510466.REJECTED.json` 마커.
- reason: "The Holocaust Explained 단일 article/subtopic page — 게시판 아님. 폴링 대상 X."
- note: "같은 문서 안 subtopic anchor 를 게시글 목록으로 감시하지 않음. 최신 글 목록/피드 URL이 있으면 그 URL로 등록 필요."

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** 이 사이트의 article/subtopic URL 은 config 생성 대상 아님.
- **2b (--article-url) — X.** first article 교정 문제가 아니라 단일 문서 구조.
- **2c (probe heuristic) — 후보.** same-page fragment/subtopic-only 후보를 non-board 로 거부하는 신호 가능. 일반 anchor table-of-contents false positive 우려로 이번엔 코드 변경 안 함.
- **2d (probe artifact 수정) — X.** row 후보 자체는 관찰됨.

일반화 안 되는 이유: anchor/subtopic 구조는 docs 사이트에서 정상 navigation 으로도 쓰여 false positive risk 있음. 이번은 slug REJECTED + learned blacklist 로 좁게 차단.

## 자가 점검 (§6)
1. **자리**: none (정책 거부).
2. **이전 케이스**: single-article-page policy rejects 와 동일 축.
3. **누구 깰까**: 0 (tracked code/config 변경 없음).
4. **검증**: REJECTED marker 로 `is_registered=False` 경로.
5. **outcome=rejected_with_policy, fix_layer=none**.
6. **fixture**: skip (코드 변경 없음).
7. **트랙 B 0건 사유**: 위 §트랙 B.
