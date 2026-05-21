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

### 대칭 확장 (2026-05-21) — accept-path content-reject

분류기는 `index`/`content` 대칭 출력인데 위 Decision 은 *거부 경로*(게이트 reject → index 면 구출)에만 썼다. 같은 분류기를 **수락 경로**에도 적용: 구조 게이트 *전부 통과* 후 `_accept_path_content_reject` 가 분류기 `content`(conf≥**0.7**) 면 거부(rc=3, `note="classifier: accept_path_content"`, learn=False). 게이트가 놓친 false-accept(비-게시판이 게이트 다 뚫고 등록 → 폴링 junk 영구/generation 헛돔)를 차단.

- 같은 register 호출의 memoized 분류 1콜 공유 — 게이트 reject 없이 통과한 등록은 여기서 첫 1콜(이전 0콜). 등록은 사이트당 1회라 비용 bounded(폴링 무관).
- **비대칭 임계**: 구출(override) conf≥0.5 / 거부(reject) conf≥0.7 — recall 우선 *유지*하되 *확신 있는* 비-게시판만 거부. article precision 1.000 → 진짜 게시판 오거부 ~0.
- `?`/저신뢰 → 수락 유지(fail-safe). `--gate-only` → skip. 알려진 플랫폼(discourse/xenforo recognize fast-path)은 board_shape 도달 전 early-return → 영향 없음.
- **철학 전환**: 원안의 "false-accept 허용(recall 우선)" tradeoff 를 *부분* 되돌림 — 사용자 결정(2026-05-21): "비-게시판 등록되어 triage/폴링 오염되는 게 더 큰 손해". 단 보수적 임계로 recall 손실 최소.

## Consequences

- **득**: false-reject 핵심(SPA·marketing-root·nav-only 오발화) 회복. wired 검증 6/6(보드 4 구출, article 2 거부유지). 게이트별 사이트 escape 주석 누적 압력↓.
- **실**: 결정적→확률적 거부. 게이트가 옳게 거부하던 비-게시판을 분류기가 "index" 로 통과시킬 수 있음(false-accept) → generation 헛돔. 사용자 "확실히 게시판 아닌 것만 거부" 선호 → 허용 tradeoff(graceful fail). would-be-reject 당 +1 gemini 콜. temperature=0 이나 LLM 비결정 가능 — 동일 URL 재등록 시 결과 흔들릴 여지(낮음).
- **미해결(별도 트랙)**: SPA 보드는 분류기도 정적 HTML 론 약함 — 진짜 해법은 render(playwright). classifier outage 시 영구 REJECTED 마커(learn=False 라 재등록 회수 가능) — fail-open 전환은 추후 판단.

설계·PoC 전말: `docs/plans/llm-index-content-classifier.md`. arXiv 2505.06972, trafilatura(Boilerpipe 계열) 차용은 `docs/webclaw 차용 검토.md §2-4` 결정의 연장.
