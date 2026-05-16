---
slug: host_en-wikipedia-or_wiki_082a72a9
url: https://en.wikipedia.org/wiki/Nazi_Party
status: 🚫 거부 (단일 Wikipedia article page — 게시판 아님. 폴링 대상 X)
outcome: rejected_with_policy
date: 2026-05-16
failure_keys: [post_id_stable_shape, in_article_wiki_links, not_a_board]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [wikipedia, single-article-page, not-a-board, policy-reject]
requested_by: unknown
---

## 무엇이 일어났나
대상 URL 은 Wikipedia `Nazi_Party` 단일 article page. 자동 생성 config 는 본문 내부 `/wiki/...` 링크를 게시글 row 로 해석했고, 일부 정상 wiki slug 의 괄호/길이 때문에 `post_id_stable_shape` 에서 실패했다.

기존 `host_ko-wikipedia-or_wiki_3e20b56a` case 와 동일하게, Wikipedia article page 는 notice-watcher 의 polling 대상 게시판이 아니다. 본문 내부 링크를 감시하면 article 변경/신규 공지가 아니라 임의 참고 링크 목록을 추적하게 된다.

## 무엇을 바꿨나 (정책 거부)
`output/poll_state/host_en-wikipedia-or_wiki_082a72a9.REJECTED.json` 마커.
- reason: "단일 Wikipedia article page(/wiki/<title>) — 게시판 아님. 폴링 대상 X."
- note: "페이지 변경 감시가 목적이면 Wikipedia watchlist/RSS/최근바뀜 같은 별도 URL이 필요. 본문 내부 링크는 게시글 목록으로 보지 않음."

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** Wikipedia `/wiki/<title>` article URL 은 거부 대상이지 config 생성 대상 아님.
- **2b (--article-url) — X.** first article 교정 문제가 아님.
- **2c (probe heuristic) — 후보.** `is_article_page_url` 휴리스틱으로 단일 wiki article 사전 거부 가능. 단, MediaWiki 기반 사이트의 실제 목록/분류 페이지 false positive 우려로 이번엔 코드 변경 안 함.
- **2d (probe artifact 수정) — X.** artifact 오작동 아님.

일반화 안 되는 이유: 이미 `ko.wikipedia.org/wiki/*` learned blacklist 가 있고, 이번은 `en.wikipedia.org/wiki/*` 를 slug/learned marker 로 좁게 추가하는 편이 안전하다.

## 자가 점검 (§6)
1. **자리**: none (정책 거부).
2. **이전 케이스**: `host_ko-wikipedia-or_wiki_3e20b56a`.
3. **누구 깰까**: 0 (tracked code/config 변경 없음).
4. **검증**: REJECTED marker 로 `is_registered=False` 경로.
5. **outcome=rejected_with_policy, fix_layer=none**.
6. **fixture**: skip (코드 변경 없음).
7. **트랙 B 0건 사유**: 위 §트랙 B.
