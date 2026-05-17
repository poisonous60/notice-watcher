---
slug: host_developer-mozil_ko_47b50435
url: https://developer.mozilla.org/ko/docs/Web/HTML/Reference/Elements/button
status: ❌ 거부 (MDN docs reference 단일 페이지 — 게시판 아님)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, single_article_page, posts_nonempty_zero, docs_reference_page]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [reject-marker, recognizer-fast-path, mdn-docs, single-article]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview https://developer.mozilla.org/ko/docs/Web/HTML/Reference/Elements/button` → 자동 등록 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] posts_nonempty: 0건` + `[warn] matches_probe_first_article: probe first_article_url='https://developer.mozilla.org/ko/docs/Web/HTML/Reference/Elements/a' 와 일치하는 글 URL 없음` + `[warn] count_ballpark: 0건 (probe 후보 child_count≈128)`.

## 진단

`diagnosis.json` `verdict='정적 HTTP로 충분'`, `article_entry_ok=True`. 게이트 통과 이유:
- `nav_only_same_host=False` (outside_nav=4 — main content 안 element nav 의 element 링크가 nav 밖 inline `<a>` 라 nav-only 미발동)
- `article_meta_signals=None` (MDN docs 가 og:type=article 박지 않음)
- `row_external_host.external_ratio=0.0` (모두 same-host)

→ board_shape_check 통과 → Gemini 가 sidebar element list 를 row 로 잡았으나 실제 selector 가 페이지 구조 안 맞아 `posts_nonempty=0`. MDN docs 는 *reference 단일 페이지* — 게시판 X.

매칭 `docs/config 자동생성 실패 케이스.md §2g (not_a_board)`.

## 픽스 (트랙 A + B — fix_layer=F)

트랙 A: `.REJECTED.json` 마커 박음 + `triage_queue.jsonl` cleanup.

트랙 B: `engine/recognizers/article_page_reject.py:PATTERNS_REJECT` 에 MDN 패턴 추가 — `developer.mozilla.org/<lang>/docs/<path>` 매칭. `skip_learn=True` (host_path_prefix=lang 이라 학습은 안전하지 X — MDN Blog `/<lang>/blog/` 미래 등록 자체는 다른 path-prefix 라 영향 X). 미래 같은 호스트 docs URL `/watch` 즉시 차단.

같은 PR 인프라 case: `docs/cases/infra_article_page_reject_3_2026-05-17.md`.

## 트랙 B 후보 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ MDN 패턴 추가.
- **2b (--article-url)**: ❌ — 입력이 single docs page 자체.
- **2c (probe heuristic)**: ❌ skip — `external_ratio>=0.95` 등 multi-host hub 휴리스틱 후보였으나 운영 `host_poly-pizza_root_a38820de` (external_ratio=1.0/total=1) false-positive 위험 → 보수적으로 PATTERNS_REJECT 만. 같은 패턴 미커버 호스트 1건 더 들어오면 휴리스틱화 재검토.
- **2d (probe artifact 수정)**: ❌ — artifact 정상.
