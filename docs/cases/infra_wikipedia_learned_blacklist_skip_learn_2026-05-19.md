---
slug: infra_wikipedia_learned_blacklist_skip_learn_2026-05-19
url: https://en.wikipedia.org/wiki/Special:RecentChanges?hidebots=1&hidecategorization=1&hideWikibase=1&limit=50&days=1&urlversion=2
status: ✅ 일반화 (recognize_reject wikipedia 패턴 skip_learn=True)
outcome: improved
date: 2026-05-19
failure_keys: [learned_blacklist_overbroad, shared_path_prefix_board, not_a_board]
fix_layer: F
config_strategy: none
adapters_changed: []
engine_files_touched: [engine/recognizers/article_page_reject.py]
tags: [learned-blacklist, skip-learn, wikipedia, url-gate, recognize-reject, track-b]
requested_by: 초카구야공주재밌어요
---

## 무엇이 일어났나

사용자가 `https://en.wikipedia.org/wiki/Special:RecentChanges?hidebots=1&...` 를 봇 `/watch`/`/preview` 로 시도. 봇이 거부:

> ⚠️ 이전 시도에서 거부된 패턴이에요 — 사유: 단일 Wikipedia article page(/wiki/<title>) — 게시판 아님. 폴링 대상 X. 참고 URL: https://en.wikipedia.org/wiki/Nazi_Party

`Special:RecentChanges` 는 위키 *전체* 의 최근 변경 board — 폴링 적합. 위키 단일 article 거부 (`/wiki/Nazi_Party`, case `host_en-wikipedia-or_wiki_082a72a9`, 2026-05-16) 가 `output/learned_blacklist.json` 에 host=`en.wikipedia.org` + path_prefix=`/wiki` 로 학습돼 같은 첫 path segment 를 공유하는 보드까지 url_gate 단에서 차단.

## 진단

- `engine/recognizers/article_page_reject.py` 의 wikipedia 패턴은 negative look-ahead `(?!Special:|Category:|Portal:|...)` 로 보드 URL 통과 시킴 — 그 자체는 정확.
- 그러나 `recognize_reject` 매칭 후 `_save_rejected(learn=True)` → `_learn_pattern` → `_extract_url_pattern` ([scripts/register.py:364-388](scripts/register.py#L364-L388)) 이 path 의 *첫 segment* 만 학습. wikipedia 의 모든 페이지가 `/wiki/...` → path_prefix=`/wiki` 한 자리.
- 다음에 `/wiki/Special:RecentChanges` 가 들어오면 `bot/url_gate.py` 의 학습 룰 (host=`en.wikipedia.org` + path_prefix=`/wiki`) 가 매칭 → 보드인데 차단.

이 패턴은 nature/iln-ieee/jobplanet/MDN/tistory 에서 이미 `skip_learn=True` 로 처리된 케이스 (보드와 article 이 같은 첫 path segment 공유). wikipedia 만 빠져 있었음.

## 무엇을 바꿨나

**Track A (즉시) + Track B (일반화) 같은 PR**:

1. `engine/recognizers/article_page_reject.py` — wikipedia 패턴을 2-tuple → 3-tuple `skip_learn=True`. 주석에 사유 박음. recognize_reject 의 article 거부는 그대로 유지 (negative look-ahead 동작 X — 단일 article 페이지만 거부).
2. `tests/recognizers/test_article_page_reject.py` — 기존 case #26 (`wikipedia_skip_learn_false` → `wikipedia_skip_learn_true`) flip + case #26b 추가 (Special:RecentChanges + 쿼리 통과). 44 PASS.
3. `output/learned_blacklist.json` — 기존 entry 두 개 unlearn (dev box):
   - `5b33425f47fd` (en.wikipedia.org + `/wiki`)
   - `81664de75d24` (ko.wikipedia.org + `/wiki`)
4. N100 도 같은 unlearn 필요 — §5 deploy step.

## 트랙 B (일반화 검토)

- **2a (인식기) — 동일 PR.** wikipedia 패턴 skip_learn flip = 같은 정책의 적용.
- **2b (--article-url) — X.** first article 교정 문제 아님.
- **2c (probe heuristic) — X.** probe 안 옴 (url_gate 차단).
- **2d (probe artifact) — X.**
- **2e (손-config) — X.**

추가 일반화 후보 (별 PR):
- `_extract_url_pattern` 가 *항상* 첫 segment 만 봄 — 일부 호스트는 더 좁은 prefix 가 정확 (예: `/wiki/Special` 한 단계 더). 그러나 두 segment 가 article-vs-board 경계인 경우는 드물고, 더 위험 (좁아도 보드 차단 가능). 현 `skip_learn` 명시 annotation 이 더 안전.

## 자가 점검 (§6)

1. **자리**: F (recognizer pattern 변경 — `engine/recognizers/article_page_reject.py` 의 tuple 형식 변경 + 정책 의도). (E)/(D)/(C)/(B)/(A) 매핑 X — recognize_reject 의 결과 contract 변경.
2. **이전 케이스 누적**:
   - `not_a_board` 13건 (track_b_trigger=true) — 비슷한 정책 거부 호스트들.
   - `signal=skip_learn` 15건 (track_b_trigger=true) — nature/iln-ieee/jobplanet/MDN/tistory 도 같은 정책 적용. 이번 wikipedia 가 동일 자리에 박힘.
3. **누구 깰까**: configs/ 21+ 사이트 영향 X (recognize_reject 는 config 생성 X). 영향 = wikipedia article URL 차단은 그대로, learned_blacklist 학습만 skip. 영향 0개.
4. **검증**:
   - `python tests/recognizers/test_article_page_reject.py` — 44 PASS.
   - `python scripts/probe_smoke.py --stage 3 --stage 5` — 358 PASS 0 FAIL.
   - `python -m bot.url_gate "<Special:RecentChanges URL>" --no-gsb` — 통과.
   - 회귀 검증: stage 1/2 의 6 FAIL 은 *pre-existing* (recent Phase 6 robots `sitemaps` key) — 본 PR 변경 영향 X (stash 후 동일 6 FAIL 확인).
5. **outcome=improved, fix_layer=F** (recognizer 정책 변경 — 1 라인 tuple shape 이지만 cross-host policy 의 일관성 통합).
6. **fixture**: tests/recognizers/test_article_page_reject.py case #26 + #26b. probe heuristic 추가 X.
7. **트랙 B**: 위 §트랙 B.
8. **vocab_candidates**: 없음 (engine strategy/source/transform 어휘 한계 아님).
