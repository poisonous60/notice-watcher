---
slug: host_github-wiki-see_m_6c370ddf
url: https://github-wiki-see.page/m/goofcode/UR/wiki/%EB%85%BC%EB%AC%B8-%EC%9D%BD%EB%8A%94-%EB%B2%95%2C-Survey-%EB%85%BC%EB%AC%B8-%EC%93%B0%EB%8A%94%EB%B2%95
status: ❌ 거부 (github-wiki-see.page wiki 미러 단일 페이지 — 게시판 아님)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, single_article_page, post_id_stable_shape, wiki_mirror, external_only_links]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [reject-marker, recognizer-fast-path, wiki-mirror, single-article, external-only]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview <wiki-page-url>` → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] post_id_stable_shape: 안정적 ID 모양 아님(공백 등): ['%EB%85%BC%EB%AC%B8-%EC%9D%BD%EB%8A%94-%EB%B2%95%2C-Survey-%EB%85%BC%EB%AC%B8-%EC%93%B0%EB%8A%94%EB%B2%95']` + `[warn] matches_probe_first_article: probe first_article_url='http://blizzard.cs.uwaterloo.ca/keshav/home/Papers/data/07/paper-reading.pdf' 와 일치하는 글 URL 없음`.

## 진단

`diagnosis.json` `verdict='정적 HTTP로 충분'`, `article_entry_ok=False`. 게이트 통과 이유:
- `nav_only_same_host=None` (same-host repeating pattern 0건)
- `article_meta_signals=None`
- `row_external_host.external_ratio=1.0` total=1 (page 안 *유일한* row 가 외부 PDF 참고 링크)

→ board_shape_check 통과 (`html_repeating_patterns` 0 + `first_article_url=external` 이지만 `n_html_same` 0 으로 떨어져야 하는데 자세히 보면 `first_article_url` 자체가 same-host check 통과 못 함). 그러나 Gemini 가 페이지를 *단일 글 페이지* 인 채 row_selector=`#content` 로 잡고 post_id 를 URL slug (한글-encoded) 로 박음 → `post_id_stable_shape` FAIL.

매칭 `§2g (not_a_board, single article + external-only links)`.

## 픽스 (트랙 A + B — fix_layer=F)

트랙 A: `.REJECTED.json` 마커 + learned_blacklist (host_suffix=`github-wiki-see.page`, path_prefix=`/m`) 박힘. `skip_learn=False` (호스트 전체가 wiki 미러 — article-only).

트랙 B: `article_page_reject.py:PATTERNS_REJECT` 에 `github-wiki-see\.page/m/<user>/<repo>/wiki/` 추가. 미래 같은 호스트 wiki page 즉시 차단.

같은 PR 인프라 case: `docs/cases/infra_article_page_reject_3_2026-05-17.md`.

## 트랙 B 후보 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ github-wiki-see 패턴 추가.
- **2b (--article-url)**: ❌ — single article 페이지.
- **2c (probe heuristic — `_external_only_check`)**: ❌ 보류. `external_ratio=1.0` + `total=1` 게이트가 운영 `host_poly-pizza_root_a38820de` (sponsor link total=1) false-positive 차단 위험. 같은 패턴 미커버 호스트 1건 더 들어오면 재검토.
- **2d (probe artifact 수정)**: ❌.
