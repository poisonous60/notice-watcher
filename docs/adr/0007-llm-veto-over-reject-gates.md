# 거부 게이트 — 결정적 휴리스틱 → LLM index/content 분류기 veto

## Context

`scripts/register.py` 는 LLM config 생성 *전*, 5개 구조 휴리스틱 게이트로 "게시판(board) 아님" 을 판정해 `rc=3 gate_reject` 로 거부한다: `_single_article_nav_only_check` · `_meta_article_diverging_check` · `_multi_host_hub_check` · `_root_marketing_homepage_check` · `_board_shape_check`.

문제: 사이트 다양성 > 룰 추가 속도. 매 batch 마다 *진짜 게시판*을 "아님" 으로 거부하는 false-reject 발생 → 게이트마다 사이트별 escape 주석 누적(주먹구구). 근본 비대칭은 "게시판임의 *증거 부재*(`board_shape` 의 same-host 신호 합<1)" 로 거부하는 결정 구조 — probe 가 SPA/지연렌더를 못 잡으면 멀쩡한 게시판이 거부됨.

학계: index page(목록) vs content page(단일글) 분류는 LLM 으로 F1 0.89 / precision 0.98 (arXiv 2505.06972, title+body). 휴리스틱 baseline 천장은 F1 0.78. PoC 실측(gemini-2.5-flash, trafilatura 추출): board recall 0.905 / article precision 1.000, 잔여 miss 2건은 둘 다 SPA(현 게이트도 거부 = regression 0).

## Decision

5개 구조 게이트의 hard-reject 를 **LLM 분류기 veto** 로 감싼다. 게이트가 거부하려 할 때 `classify_index_content` 호출 → `index`(conf≥0.5) 면 **거부 취소**(일반 파이프라인 계속), `content`/실패 면 기존대로 거부.

- 입력 = `digest["list_html"]["source"]` raw HTML(trafilatura title+body) + `list_candidates` 구조 신호. cleaned `["html"]` 은 200KB cap 으로 SPA 본문 잘림 → source 우선.
- veto 는 `_save_rejected` *전* → override 시 마커·learned_blacklist 미발생.
- register 호출당 1회 memoize(digest 캐시) — 5게이트 + root_marketing 내부 board_shape 콜이 단일 verdict 공유(drift 불가, +1 LLM 콜만).
- `--gate-only` 는 veto skip(LLM 0콜 보장).
- 분류 실패/HTML 부재/trafilatura 미설치 → `class="?"` → 거부 유지 = **fail-safe**(status-quo, regression 0).

**veto 유지(거부 취소 안 함)**: `recognize_reject`(host 명시 known-article PATTERNS) + capability_blocked(rc=5 captcha) — 고정밀·false-reject 원인 아님.

## Consequences

- **득**: false-reject 핵심(SPA·marketing-root·nav-only 오발화) 회복. wired 검증 6/6(보드 4 구출, article 2 거부유지). 게이트별 사이트 escape 주석 누적 압력↓.
- **실**: 결정적→확률적 거부. 게이트가 옳게 거부하던 비-게시판을 분류기가 "index" 로 통과시킬 수 있음(false-accept) → generation 헛돔. 사용자 "확실히 게시판 아닌 것만 거부" 선호 → 허용 tradeoff(graceful fail). would-be-reject 당 +1 gemini 콜. temperature=0 이나 LLM 비결정 가능 — 동일 URL 재등록 시 결과 흔들릴 여지(낮음).
- **미해결(별도 트랙)**: SPA 보드는 분류기도 정적 HTML 론 약함 — 진짜 해법은 render(playwright). classifier outage 시 영구 REJECTED 마커(learn=False 라 재등록 회수 가능) — fail-open 전환은 추후 판단.

설계·PoC 전말: `docs/plans/llm-index-content-classifier.md`. arXiv 2505.06972, trafilatura(Boilerpipe 계열) 차용은 `docs/webclaw 차용 검토.md §2-4` 결정의 연장.
