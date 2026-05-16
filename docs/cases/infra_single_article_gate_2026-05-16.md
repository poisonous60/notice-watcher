---
slug: infra_single_article_gate_2026-05-16
url: (인프라 case — 특정 사이트 X. 트리거 = beec51d 의 article-page 4건 손-거부 직후)
status: 🏗 인프라 (단일 article page 자동 거부 게이트 — 인식기 fast-path + nav-only 구조 fallback)
outcome: improved
date: 2026-05-16
fix_layer: F+C
failure_keys: [single_article_page, board_shape_false_positive, nav_only_same_host, recognizer_reject_fast_path]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, engine/recognizers/__init__.py, probe/extract.py, probe/_contract.py, scripts/probe.py, scripts/register.py, tests/probe_heuristics/test_all_same_host_patterns_in_nav.py, tests/recognizers/test_article_page_reject.py]
tags: [self-improvement, probe-heuristic, recognizer-fast-path, article-page-reject, nav-only, board-shape-gap]
requested_by: 운영자 (dev box session)
---

## 트리거

직전 처리 (commit `beec51d`) 에서 codex 가 4 건 article-page 손-거부 (britannica/en-wiki/encyclopedia-us/holocaust) + 그 전 `dd5ea0d` 에서 ko-wiki/terms 손-거부. 6 사이트 동일 패턴 = *단일 article page 인데 `_board_shape_check` 의 `n_html_same` 가 in-page 링크/사이드바 메뉴에 false-positive 트리거 → board 로 오인 → gemini 4회 시도 → 실패 → triage 큐 오염*.

사용자 의도: "사이트 하나하나 block 하는 걸론 끝이 없고 결국 probe 의 성능을 올려야 함." → **자동화 휴리스틱 도입** (트랙 B = 2c probe heuristic).

## 픽스 (fix_layer: F+C — 8 파일)

### F-1. `engine/recognizers/article_page_reject.py` 신규 — 호스트 명시 fast-path

알려진 백과/사전 호스트 (wikipedia/terms.naver/britannica/encyclopedia.ushmm) 의 단일 article URL 패턴을 `PATTERNS_REJECT` 로 export. 일반 인식기(`PATTERNS`) 와 달리 *config 생성 X*, reject reason 만 반환.

PATTERNS (negative-lookahead 로 분류/Special/Category 페이지는 통과):
- `^https?://[a-z]{2,3}\.wikipedia\.org/wiki/(?!Special:|Category:|...|분류:|...)\S+/?$`
- `^https?://terms\.naver\.com/entry\.(naver|nhn)`
- `^https?://www\.britannica\.com/(event|topic|biography|...)/<slug>/?$`
- `^https?://encyclopedia\.ushmm\.org/content/[a-z]+/article/<slug>/?$`

### F-2. `engine/recognizers/__init__.py` — recognize_reject(url) 신규

`_load_rejects()` 가 모듈의 `PATTERNS_REJECT` 자동 수집. `recognize_reject(url) -> Optional[(name, reason)]`. URL-encoded path (`%EB%B6%84%EB%A5%98:`=`분류:`) 매칭 위해 `urllib.parse.unquote` 한 형태로 검사.

### F-3. `scripts/register.py` — recognize_reject fast-path gate

`recognize_platform` 호출 직전에 검사. 매칭 시 즉시 `_save_rejected` + `_learn_pattern` 자동 호출 후 `return 3`. probe 자체를 안 돌림 → 시간/비용 0.

### C-1. `probe/extract.py:all_same_host_patterns_in_nav` 신규 — 구조 기반 fallback

호스트 명시되지 않은 *unknown* article-like 사이트 (theholocaustexplained 류) 의 자동 검출. 알고리즘:

1. `html_repeating_patterns` 중 `sample_url.netloc == base_host` 인 same-host 패턴만 추림.
2. 각 패턴의 selector 로 DOM element 찾아 ancestor 체인 walk.
3. ancestor 중 `<nav>`/`<aside>`/`<header>`/`<footer>` 또는 `role=navigation|complementary|banner|contentinfo` 가 있으면 "in_nav" 카운트, 없으면 "outside_nav".
4. `outside_nav == 0` (= 모든 same-host pattern 이 nav 안) → `nav_only_same_host: True` → single-article 신호.

검증 (8 fixture, false positive 0):

| site | total_same_host | in_nav / outside_nav | verdict | 실제 |
|---|---|---|---|---|
| omate (BOARD) | 6 | 5 / 1 | board | board ✅ |
| gamemeca (BOARD) | 7 | 0 / 7 | board | board ✅ |
| quibli (BOARD) | 3 | 2 / 1 | board | board ✅ |
| holocaust (ART) | 3 | 3 / 0 | **single** | article ✅ |
| ko-wiki (ART) | 8 | 2 / 6 | board | article (인식기 cover) |
| britannica (ART) | 7 | 0 / 7 | board | article (인식기 cover) |
| encyclopedia-us (ART) | 7 | 5 / 2 | board | article (인식기 cover) |
| en-wikipedia (ART) | 6 | 1 / 5 | board | article (인식기 cover) |

→ nav-only 휴리스틱 false positive 0 + holocaust 류 *unknown host* 1건 자동 커버. 나머지 article 페이지는 인식기 fast-path 가 잡음. 두 신호 보완 관계 ✅.

### C-2. `probe/_contract.py` + `probe/extract.py:write_list_candidates` + `scripts/probe.py`

`list_candidates.json` payload 에 `nav_only_same_host` 새 키 추가 (`dict|null`, required=False). probe.py 가 휴리스틱 호출하여 결과 박음.

### F-4. `scripts/register.py:_single_article_nav_only_check` — gate

`_board_shape_check` *직전* 호출. `digest.list_candidates.nav_only_same_host.nav_only_same_host == True` 면 즉시 거부 (`_learn_pattern` + `return 3`). board_shape 의 `n_html_same >= 1` false-positive 우회 차단.

## 테스트

- `tests/probe_heuristics/test_all_same_host_patterns_in_nav.py` (6 case) — board 통과 / nav-only single 거부 / role-nav 인정 / same-host 0건 None / empty html None / empty base None.
- `tests/recognizers/test_article_page_reject.py` (18 case) — wikipedia/terms/britannica/USHMM positive + 분류:/Special:/list 통과 negative + 일반 board (omate/arca) 통과 + holocaust 통과 (이건 nav-only 가 잡음).

## 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` → **275 PASS / 0 FAIL** (35 configs 전부 OK + 27 heuristic test 파일 / 239 case).
- 기존 운영 21 configs 의 list_url 중 og:type=article 가진 것 3 건 (omate/gamemeca/quibli) — 모두 새 nav-only gate 통과 (in_nav < outside_nav 또는 outside_nav ≥ 1). 직접 unit test 로 확인.

## 트랙 B (일반화 후보) — 자가 검토

- **2a (인식기)**: F-1 으로 직접 수행. wikipedia/terms/britannica/USHMM 4 호스트.
- **2b (--article-url)**: X — 입력이 단일 article URL 자체라 교정 대상 없음.
- **2c (probe heuristic)**: C-1 로 직접 수행. nav-only structure fallback.
- **2d (probe artifact 수정)**: X — artifact 정상 (`html_repeating_patterns` 가 nav 안 패턴까지 정확히 잡았음, 신호 *해석* 안 됐던 것).

## 자가 점검 (§6)

1. **자리**: F (engine/recognizers/ + scripts/register.py 새 gate) + C (probe/extract.py 새 휴리스틱).
2. **이전 케이스**: `host_ko-wikipedia-or_wiki_3e20b56a`, `host_terms-naver-com_entry.naver_a297b3b0`, `host_britannica-com_event_655a158c`, `host_en-wikipedia-or_wiki_082a72a9`, `host_encyclopedia-us_content_fba2a7a9`, `host_theholocaustexp_the-nazi-rise-to-power_9f510466` — 모두 동일 패턴 (단일 article page false-positive board_shape 통과).
3. **누구 깰까**: 기존 운영 21 configs 중 og:type=article 보유 3 건 (omate/gamemeca/quibli) — 모두 nav-only gate 통과 확인 (outside_nav ≥ 1). 회귀 0.
4. **검증**: probe_smoke stage 3+5 PASS 275/0. 새 fixture 6+18=24 case 0 fail.
5. **outcome=improved, fix_layer=F+C**.
6. **fixture (§7,§8 의무)**:
   - 새 strategy 추가 X — `REPS` 변경 안 함 (§7 skip).
   - 새 휴리스틱 `all_same_host_patterns_in_nav` (`@heuristic` 데코) + `tests/probe_heuristics/test_all_same_host_patterns_in_nav.py` 짝 — §8 만족.
7. **트랙 B**: 위 §트랙 B 4 항목 모두 enumerate.
