---
slug: host_tistory-com_root_c59077fa
url: https://www.tistory.com/
status: ❌ 거부 (Tistory 메인 멀티-블로그 hub — 게시판 아님)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, multi_host_hub, post_id_stable_shape, tistory_root]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [reject-marker, recognizer-fast-path, multi-host-hub, tistory]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview https://www.tistory.com/` (Tistory 플랫폼 메인) → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] post_id_stable_shape: 안정적 ID 모양 아님(공백 등): ['%EC%A7%84%EC%9E%91-%EC%95%8C%EC%95%98%EC%9C%BC%EB%A9%B4-%EC%A2%8B%EC%95%98%EC%9D%84-%EA%BF%80%ED%85%9C-3%EA%B0%80%EC%A7%80-%EC%B6%94%EC%B2%9C']` + 추출된 글들이 *서로 다른 서브도메인* (`ohokja1940.tistory.com`, `everylittle.tistory.com`, `michan1027.tistory.com`, `fisher0099.tistory.com`, `yujj.tistory.com` …).

## 진단

`diagnosis.json` `verdict='정적 HTTP로 충분'`, `article_entry_ok=True`. 게이트 통과 이유:
- `nav_only_same_host=None` (`base_host=www.tistory.com` same-host pattern 0 — row 들이 *다른 서브도메인*)
- `article_meta_signals=None`
- `row_external_host.external_ratio=1.0` total=3 (sample: `policy.daum.net`, `ohokja1940.tistory.com`, `breezehu.tistory.com` — 3 unique 외부 호스트)

→ `www.tistory.com/` 메인 페이지는 *여러 블로그 인기글* 모음. 단일 board X — 멀티-host hub. 각 row 가 다른 블로그 → post_id 가 어떤 블로그는 numeric (`1976`), 어떤 블로그는 한글-encoded slug (`%EC%A7%84%EC%9E%91-...`) → `post_id_stable_shape` FAIL.

매칭 `§2g (not_a_board, multi-host hub)`.

## 픽스 (트랙 A + B — fix_layer=F)

트랙 A: `.REJECTED.json` 마커 (learned_blacklist 학습은 skip_learn=True 라 *안 박힘* — 의도된 동작).

트랙 B: `article_page_reject.py:PATTERNS_REJECT` 에 `(?:www\.)?tistory\.com/` 추가. `skip_learn=True` — host=`www.tistory.com` path=`` 학습이 모든 path 차단해 hub 다른 변형 (`/?category=...`) 까지 막을 위험 (보드 없는 hub 라 사실상 안전이지만 보수).

**개별 블로그 영향 X**: `<subdomain>.tistory.com/<post_id>` (예: `ohokja1940.tistory.com/1976`) 는 *별도 host* — recognizer 패턴 매칭 X, 학습 안 됨. 개별 블로그 등록은 자유.

같은 PR 인프라 case: `docs/cases/infra_article_page_reject_3_2026-05-17.md`.

## 트랙 B 후보 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ tistory.com root 패턴 추가.
- **2b (--article-url)**: ❌ — multi-host hub 자체.
- **2c (probe heuristic — `_multi_host_hub_check`)**: ❌ 보류. `external_ratio>=0.95 AND len(unique_external_hosts)>=3` 신호가 multi-host hub 만 명확히 잡으나 — 현재 같은 패턴 1건째 (tistory 메인). 같은 패턴 2건째 (`brunch.co.kr/`, `steemit.com/trending` 등) 들어오면 휴리스틱화 재검토. 단일 케이스에서 일반 휴리스틱 박는 건 over-engineering.
- **2d (probe artifact 수정)**: ❌.
