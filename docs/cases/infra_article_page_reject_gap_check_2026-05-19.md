---
slug: infra_article_page_reject_gap_check_2026-05-19
url: tests/recognizers/test_article_page_reject.py
status: ✅ 일반화 (programmatic gap-check + docstring sync)
outcome: improved
date: 2026-05-19
failure_keys: [learned_blacklist_overbroad, shared_path_prefix_board, fixture_gap]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [test-hardening, programmatic-guard, codex-review, learned-blacklist, skip-learn]
requested_by: codex review (commit b13f4af + 8d61d99 후속)
---

## 무엇이 일어났나

wikipedia (commit `b13f4af`) + USHMM (commit `8d61d99`) 의 `skip_learn=True` flip 후 사용자가 codex 리뷰 호출. codex 리뷰 5개 질문 응답 (Q1~Q5):

- **Q1 (tuple contract)**: callsite OK. test file `:3` 모듈 docstring stale (`(NAME, reason)` 표기) — minor.
- **Q2 (mtime race)**: 안전 (over-block fail mode 만 가능, under-block X).
- **Q3 (first-segment policy 일반화)**: docstring 룰만 있고 *programmatic guard 없음* — author miss 시 안 잡힘. 새 PATTERNS_REJECT 호스트 추가 시 보드 first-segment 공유 누락 detect 위한 자동 가드 권장.
- **Q4 (fast-path 손실)**: url_gate 학습 fast-path 없어진 만큼 recognize_reject regex 평가 (sub-ms). 같은 URL 반복은 `bot/site_ops.py:is_rejected` 의 REJECTED.json marker 가 흡수 — 실제 사용자 체감 차이 거의 없음.
- **Q5 (fixture coverage gap)**: ktword 는 highest-confidence unguarded gap (별 PR 후보, 사용자 보류). github-wiki-see/sumo 는 unconfirmed (host 전체 article-only 가정 OK).

## 무엇을 바꿨나

1. `tests/recognizers/test_article_page_reject.py:3` — 모듈 docstring 수정. `(NAME, reason)` → `(NAME, reason, skip_learn)` 3-tuple + `__init__.py` 가 2-tuple 패턴을 skip_learn=False 로 정규화한다는 사실 명시 + gap-check 루프 언급.
2. 같은 파일 끝 `SAME_SEG_GAP_CHECKS` 신규 — codex Q3 의 programmatic guard. 7개 호스트 (wiki_en/wiki_ko/ushmm/nature/iln_ieee/jobplanet/mdn) 의 `(article_url, board_url)` 페어를 enumerate. 각각:
   - `recognize_reject(article_url)` 가 skip_learn=True 로 거부
   - `recognize_reject(board_url)` 가 통과
   - 두 URL 의 `(host, first_path_segment)` 가 동일
   세 조건 동시 만족 검사. 새 호스트 추가 시 보드와 first segment 공유면 여기 한 줄 추가 — 누락 시 fixture 실패로 즉시 catch.
3. ktword 별 PR 후보 명시 (코멘트). github-wiki-see/sumo/openai/terms.naver/britannica/tistory 는 first-segment 공유 X (skip_learn=False 안전) 명시.

### 코드 변경 X
- Q2 (race) — fail mode 가 over-block 방향이라 안전. 코드 변경 X.
- Q4 (latency) — REJECTED.json marker 가 repeat URL 흡수. 실측 perf 회귀 없음. 코드 변경 X.
- ktword (Q5) — 실페이지 확인 후 별 PR.

## 트랙 B (일반화 검토)

- **2a (인식기) — 적용 완료.** programmatic gap-check 이 *모든* 미래 PATTERNS_REJECT 추가에 가드. 다른 인식기/모듈로 일반화 후보는 별도 (예: PATTERNS 의 builder 결과 검증).
- **2b/2c/2d/2e — X.** test hardening only.

## 자가 점검 (§6)

1. **자리**: none (test fixture + 모듈 docstring 강화만 — engine/strategies/·adapters/·engine/recognizers/·scripts/register.py 변경 X). SKILL.md §6.1 의 6 자리 (E/D/C/B/A/F) 중 매핑 X — pure test/doc hardening 은 `fix_layer: none`. outcome=improved 는 programmatic guard 가 미래 회귀 방지 효과 있음을 표시.
2. **이전 케이스**: `infra_wikipedia_learned_blacklist_skip_learn_2026-05-19` (`b13f4af`) + `infra_ushmm_learned_blacklist_skip_learn_2026-05-19` (`8d61d99`). 동일 정책의 자동 가드화.
3. **누구 깰까**: 0개 (테스트 가드만 추가). 기존 51 test fixture 통과.
4. **검증**:
   - `python tests/recognizers/test_article_page_reject.py` — 51 PASS (기존 44 + 7 gap_check).
   - `python scripts/probe_smoke.py --stage 3 --stage 5` — 360 PASS 0 FAIL.
5. **outcome=improved, fix_layer=none** (programmatic guard 가 미래 회귀 방지 효과 → improved, 그러나 engine 코드 변경 X → fix_layer none).
6. **fixture**: 7 gap_check_<host>.
7. **트랙 B**: 적용 완료 (위).
8. **vocab_candidates**: 없음.
