---
slug: infra_ushmm_learned_blacklist_skip_learn_2026-05-19
url: https://encyclopedia.ushmm.org/content/en
status: ✅ 일반화 (USHMM 패턴 skip_learn=True + 모듈 docstring 강화)
outcome: improved
date: 2026-05-19
failure_keys: [learned_blacklist_overbroad, shared_path_prefix_board, not_a_board]
fix_layer: F
config_strategy: none
adapters_changed: []
engine_files_touched: [engine/recognizers/article_page_reject.py]
tags: [learned-blacklist, skip-learn, ushmm, url-gate, recognize-reject, track-b, audit]
requested_by: 사용자 audit 요청 (wiki case 후속)
---

## 무엇이 일어났나

사용자가 wikipedia case (`infra_wikipedia_learned_blacklist_skip_learn_2026-05-19`, commit `b13f4af`) 적용 후 "다른 잘못 분류된 사이트들도 있나" 질문. 전체 `PATTERNS_REJECT` audit 결과:

- **USHMM (강한 후보)**: `encyclopedia.ushmm.org/content/<lang>/article/<slug>` article 패턴 skip_learn=False 인데, recognize_reject test #13 명시한 인덱스 `/content/en` 이 같은 첫 segment `/content` 공유 → 위키와 동일 over-block.
- **ktword (약한 후보)**: 주석은 "host 전체 article-only" 이라 false 박았지만 test #33 `/test/abbr_view/list_letter.php` 통과 — 실페이지 확인 필요. 별도 처리 (이 케이스 제외).
- 나머지 6개 (terms.naver/britannica/github-wiki-see/openai/sumo/theholocaustexplained) 안전 (다른 첫 segment 또는 host 전체 article-only).

기존 learned entry `86d4658d1690` (host=`encyclopedia.ushmm.org`, path_prefix=`/content`) 가 박혀 있어 `/content/en` 인덱스 URL 이 url_gate 단에서 차단되던 상태.

## 무엇을 바꿨나

1. `engine/recognizers/article_page_reject.py` USHMM 패턴 2-tuple → 3-tuple `skip_learn=True`. 주석에 사유.
2. 모듈 docstring `새 호스트 추가 룰` 섹션 강화:
   - 4-step 점검 절차 (보드 URL 식별 → article 폼 명확화 → skip_learn 결정 트리 → fixture 강제).
   - 결정 트리: "article 의 *첫 path segment* 로 시작하는 *다른* URL 폼이 정상 보드/인덱스가 될 수 있는가? YES → skip_learn=True 필수."
   - wikipedia/ushmm/nature/britannica/github-wiki-see 예시 enumerate.
   - 새 호스트 fixture 강제: article URL 거부 + skip_learn 값 명시, 같은 host 의 보드 URL 통과.
3. `tests/recognizers/test_article_page_reject.py` case #12 강화: USHMM `out[2] is True` 명시. 44 PASS.
4. `output/learned_blacklist.json` 의 `86d4658d1690` unlearn (dev box). N100 도 같은 unlearn 필요.

## 트랙 B (일반화 검토)

- **2a (인식기) — 동일 PR.** USHMM skip_learn flip + docstring 강화.
- **2b/2c/2d/2e — X.** probe/config-gen 안 옴 (url_gate 차단).

별 PR 후보:
- **ktword (불확실)**: `/test/abbr_view/list_letter.php` 가 정말 보드인지 실페이지 확인 후 결정. 보드면 skip_learn=True flip.
- **선언적 link**: 새 PATTERNS_REJECT 추가하는 PR 의 pre-commit hook 으로 "article URL 첫 segment 가 같은 host 의 다른 URL prefix 와 겹치는지" 자동 점검 — 휴리스틱하지만 alert 가치. 가능성만 메모.

## 자가 점검 (§6)

1. **자리**: F (recognizer 변경 + 모듈 docstring 룰 강화). docstring 자체는 코드는 아니지만 같은 파일.
2. **이전 케이스**: `infra_wikipedia_learned_blacklist_skip_learn_2026-05-19` (commit `b13f4af`, 직전). 같은 정책의 두 번째 적용 — 동일 자리.
3. **누구 깰까**: configs/ 영향 X. USHMM `/content/<lang>` 인덱스가 다시 url_gate 통과 (이전엔 차단). recognize_reject 의 article 거부 결과 contract 동일 (단 skip_learn 값만 True 로 변경).
4. **검증**:
   - `python tests/recognizers/test_article_page_reject.py` — 44 PASS.
   - `python scripts/probe_smoke.py --stage 3 --stage 5` — 358 PASS 0 FAIL.
   - `python -m bot.url_gate "https://encyclopedia.ushmm.org/content/en" --no-gsb` — 통과.
5. **outcome=improved, fix_layer=F**.
6. **fixture**: case #12 강화.
7. **트랙 B**: 위 §트랙 B (ktword 별 PR).
8. **vocab_candidates**: 없음.
