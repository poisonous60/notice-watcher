---
slug: host_ktword-co-kr_test_d081a15f
url: http://www.ktword.co.kr/test/view/view.php?m_temp1=3801
status: ❌ 거부 (KT용어집 단일 entry — 백과형 사이트 게시판 아님)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, single_article_page, post_id_unique_duplicate, encyclopedia_entry]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [reject-marker, recognizer-fast-path, encyclopedia, single-article, ktword]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview http://www.ktword.co.kr/test/view/view.php?m_temp1=3801` (KT용어집 — "전파 모드" 단일 용어) → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] post_id_unique: 중복 1건` + 추출된 글들 (1393/5153/3801/5154/4743/...) + 본문 길이 13198자 (글 본문은 잘 추출됨).

## 진단

`diagnosis.json` `verdict='정적 HTTP로 충분'`, `article_entry_ok=True`. 게이트 통과 이유:
- `nav_only_same_host=False` (outside_nav=3 — 페이지 안 관련용어 link 들이 `pre > a` 형식, nav 밖)
- `article_meta_signals=None`
- `first_article_url='http://www.ktword.co.kr/test/view/view.php?m_temp1=2175&id=624'` (same-host) → board_shape_check 통과

→ Gemini 가 페이지 안 "관련 용어 nav tree" (`pre > a` cc=96) 를 row 로 잡음. 글 본문은 정상 추출되나 관련 용어 nav 의 *반복* 항목 중 중복 entry 있어 `post_id_unique` FAIL. KT용어집은 *백과형 사이트* — 각 페이지가 단일 용어 entry, 새 글 게시판 X.

매칭 `§2g (not_a_board, 백과)`.

## 픽스 (트랙 A + B — fix_layer=F)

트랙 A: `.REJECTED.json` 마커 + learned_blacklist (host_suffix=`www.ktword.co.kr`, path_prefix=`/test`).

트랙 B: `article_page_reject.py:PATTERNS_REJECT` 에 `www\.ktword\.co\.kr/test/view/` 추가. `skip_learn=False` — 호스트 전체가 용어집(article-only), `/test/view/`/`/test/abbr_view/` 등 모든 path 가 entry/색인 페이지라 path_prefix 학습 안전.

같은 PR 인프라 case: `docs/cases/infra_article_page_reject_3_2026-05-17.md`.

## 트랙 B 후보 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ ktword 패턴 추가.
- **2b (--article-url)**: ❌ — 단일 entry.
- **2c (probe heuristic)**: ❌ — 페이지 안 same-host nav tree 가 false-positive board 신호 통과시키는 패턴이지만 *명시 거부 게이트* 만들기엔 사이트 별 outside_nav 정의 모호. PATTERNS 가 명확.
- **2d (probe artifact 수정)**: ❌.
