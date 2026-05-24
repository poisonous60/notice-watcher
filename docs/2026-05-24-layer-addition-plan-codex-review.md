# 2026-05-24 — layer addition plan Codex review

대상: [`docs/2026-05-24-layer-addition-plan.md`](2026-05-24-layer-addition-plan.md)

---

## 1. 종합 verdict

§3 ranking 은 ζ를 제외하면 낙관적이다. production 후보 우선순위는 `ζ(bench fix)` → `γ 재측정/report artifact` → `β spike` 정도이고, α/ε/η는 현 근거로는 net 음의 EV 가능성이 더 크다.

핵심 finding:

| 항목 | 판정 | 근거 |
|---|---|---|
| α | 과상향 | MDR 단독 승리 cell 없음 (`notes_probe_vs_mdr.md` §6, `matrix.md:17-19`) |
| β | 비용 과소평가 | `_tree.pyx`, `_tree.c`, scipy `linkage/fcluster` 존재 (`mdr.py:10-11`, `:167-168`) |
| γ | 조건부 | `/report` artifact 로는 가능. `/watch` 자동복구는 부적합 (`autoscraper-triage/notes.md:176-185`) |
| δ | 비용/risk 과소평가 | sitemap 후보는 이미 prompt hint (`config_writer.system.txt:94`), 자동 Playwright 는 timeout risk |
| ε | 과상향 | bench 없음. “signal 다양화 always 양의 EV” 는 plan 자체도 noise 가능 인정 (`plan.md:84`) |
| ζ | bench fix 로는 OK | `articleNo` 추가 시 `skku_cse` posts=10 in-memory 확인 |
| η | 보류/금지 | sitemap gate 측정 in-scope 0 (`sitemap-gate-bench/notes.md:29-36`) |
| θ | 보류 | v2 는 손 config reference 수준 (`followup-v2.md:221-226`) |

---

## 2. 가정 검증

| 가정 | 확인 결과 | verdict |
|---|---|---|
| a) α “port 됨” | `experiments/prior-art-bench/tools/mdr_list_candidates_py3.py` import 성공, `list_candidates` callable | ✅ |
| b) ε “Py2→Py3 50-80 line” | `entextractor/` Py2-ish grep 39 hit: `xrange`, `iteritems`, `filter/map`, `unicode`, `BeautifulSoup`, `print` | ⚠ 문법 port 는 작아도 semantic/test 비용 누락 |
| c) β “C-ext 우회” | `_tree.pyx`, `_tree.c` 존재. `tree.py` 가 `._tree` import. `mdr.py` 가 scipy cluster 사용 | ⚠ 우회 가능하지만 1-2일 확정은 낙관 |
| d) ζ “skku 회복 확정” | `articleNo` 포함 regex 로 `skku_cse` cached HTML 분석 시 posts=10, board list picked | ✅ bench fix 로 확정에 가까움 |

관련 파일:

| 근거 | 위치 |
|---|---|
| current regex 에 `articleNo` 없음 | `experiments/prior-art-bench/tools/mdr_guarded_bench.py:25-28` |
| 현 실패: `url-pattern:1` | `experiments/prior-art-bench/results/mdr_guarded/skku_cse__run1.json` |
| `articleNo` 과차단 설명 | `experiments/prior-art-bench/notes_mdr_guarded.md:138`, `:153` |
| production URL scoring 은 더 넓음 | `probe/extract.py:484` `_article_url_score` |
| sitemap 후보 digest 포함 | `engine/digest.py:413` |
| sitemap 후보 LLM 지시 | `prompts/config_writer.system.txt:94` |
| board gate 는 sitemap 미사용 | `scripts/register.py:574-605` |

---

## 3. 항목별 review

| 항목 | 비용 평가 | noise risk 평가 | net EV | ordering |
|---|---|---|---|---|
| α MDR+probe 병합 | port 0은 맞음. 통합 30-50 LOC 는 낮음: schema/dedupe/source/prompt/test 필요 | “중”보다 높음. wrong block 확인됨 | 음수 가능 | 2위 과상향 |
| β MDR alignment | 1-2일 낮음. Cython 함수 재작성 + scipy 대체 + equivalence 필요 | 단독 후처리 낮음, wrong block 결합 시 중 | 미측정 | 5위 보류면 OK |
| γ AutoScraper | 1일은 offline 기준. bot UX/optional env/test 포함 2일+ | `/report` explicit seed 낮음. 자동 seed 중 | report artifact 양수 가능 | 3위 조건부 |
| δ playwright+sitemap | 2-3일은 prototype 기준. register timeout/lock/artifact 누락 | 중-높 맞음, 운영 risk 더 큼 | 음수 가능 | 6위도 높음 |
| ε REPS | 2-4h는 문법 port. bench/selector/test 포함 1일+ | 중보다 높을 수 있음 | 현재 음수 가능 | 4위 과상향 |
| ζ guard fix | 10 LOC + rerun 0.5일 타당 | bench-only 낮음 | 양수 | 1위 OK, 단 production layer 아님 |
| η sitemap retry | 80-120 LOC 낮음. loop/marker/rollback/test 빠짐 | 중보다 높음 | 음수 가능 | 자동화는 보류 |
| θ classifier | 50-80 LOC는 조건 정의 후에만 | signal-only 낮음 | 미측정 | 8위 보류 OK |

---

## 4. 비용 과소평가/과대평가

α:

- plan 은 `probe/extract.py:55` 옆 30-50 LOC 병합을 가정한다 (`layer-addition-plan.md:36-40`).
- 실제로는 MDR lxml element/xpath 를 `html_repeating_patterns` dict schema 로 바꾸고, selector 중복 제거, source/confidence, prompt 우선순위, regression fixture 가 필요하다.
- 비용은 0.5일보다 1-2일에 가깝다.

β:

- plan 은 pure-py 1-2일을 가정한다 (`layer-addition-plan.md:47-51`).
- `_tree.pyx` 는 작지만 `tree.py` 의 `PartialTreeAligner` 와 `mdr.py` 의 scipy clustering까지 같이 검증해야 한다.
- MSVC/Cython build 우회는 가능. 그러나 trustworthy field mapping 은 3-5일 추정.

γ:

- AutoScraper triage 는 bs4 4.13 drift, html 전달 위치 민감성, URL/post_id 미추론을 적었다 (`autoscraper-triage/notes.md:186-195`).
- stripped `_build_stack` 자체보다 `/report` UX, 저장 artifact, confidence, test 가 비용이다.

δ:

- `fetch_sitemaps` 는 이미 fail-soft 정찰이다 (`probe/discover.py:272-284`).
- `_board_like_score` 는 URL keyword/id/depth 휴리스틱일 뿐이다 (`probe/discover.py:448-465`).
- top 3 Playwright 시도는 9-15초 이상 register latency 를 늘릴 수 있다. timeout budget 이 plan 에 없다.

ε:

- Py2-ish hit 39개라 2-4h port 는 가능할 수 있다.
- 하지만 BS3→BS4 behavior, REPS output→CSS selector 변환, matrix row, false-positive fixture 를 포함하면 1일+.

ζ:

- 비용 평가는 맞다.
- 단 plan 의 “다른 사이트도 마찬가지” 는 과장이다 (`layer-addition-plan.md:94`).
- `gamemeca` 는 `url-pattern` 3 외에 `text-density/nav/same-host` 로도 모두 제거된다 (`followup-v2.md:268`, `notes_mdr_guarded.md:160-164`).

η/θ:

- η는 자동 retry loop 방지, `.REJECTED`/triage marker, 사용자 메시지, rollback 이 빠졌다.
- θ는 canva/salesforce pattern 을 일반화할 조건 정의가 아직 없다. v2 는 손 config reference 로만 봤다.

---

## 5. noise risk 과소평가

| 항목 | plan risk | review |
|---|---:|---|
| α | 중 | 높음. MDR wrong block 이 `gamemeca`/`naver`/`arca` 에서 확인됨 |
| β | 낮음 | 후처리 단독이면 낮음. α와 묶이면 중 |
| γ | 낮음 | `/report` 한정 낮음. 자동 seed 면 중 |
| δ | 중-높 | 맞음. 다만 timeout spillover 로 운영 risk 추가 |
| ε | 중 | 높음 가능. bench 없는 후보 source 추가 |
| ζ | 낮음 | bench-only 라 맞음 |
| η | 중 | 높음. 잘못된 URL 자동 등록은 prod 오염 |
| θ | 낮음 | signal-only 낮음. 자동 adapter 선택이면 중 |

α가 특히 위험한 이유:

| site | MDR 결과 | 의미 |
|---|---|---|
| `gamemeca` | n=10, match=0 | 인기게임/sidebar block |
| `naver_cafe_gutterlife` | n=7, match=0 | top nav |
| `arca_trickcal` | n=10, match=0 | pagination |

`notes_probe_vs_mdr.md` §6 은 “MDR 보조 후보 근거도 약함” 으로 결론낸다.

---

## 6. net 음의 EV 항목

| 후보 | 음의 EV 시나리오 |
|---|---|
| α | 쉬운 사이트에서 wrong MDR 후보가 prompt 에 섞여 LLM selector 선택 오염 |
| ε | nav/menu/tag 반복 후보가 prompt token 과 후보 noise 증가 |
| δ | register 단계 Playwright 추가로 timeout 증가, 기존 성공 site attempt budget 침식 |
| η | sitemap top URL 로 자동 재시도해 root/archive/article URL 을 잘못 등록 |
| β | wrong block alignment 가 그럴듯한 field selector 를 만들어 오염 |

η는 특히 보류해야 한다.

- `sitemap-gate-bench` 는 threshold 대상 0건이다.
- `prompts/config_writer.system.txt:94` 도 sitemap 후보는 실제 row pattern 과 대조하라고 한다.
- prompt hint 보다 강한 자동 retry 는 별도 측정 없이는 위험하다.

---

## 7. 우선순위 재조정 제안

현재 ranking 의 오류:

| rank | 후보 | review |
|---:|---|---|
| 1 | ζ | bench correction 으로만 OK |
| 2 | α | v2 “MDR drop” 결론과 충돌 |
| 3 | γ | 조건부 OK |
| 4 | ε | bench 전 과상향 |
| 5 | β | 보류 OK, 비용 상향 |
| 6 | δ | 직접 register 결합 전 측정 필요 |
| 7 | η | 자동화는 더 낮춰야 함 |
| 8 | θ | 보류 OK |

추천 ranking:

| 새 rank | 후보 | 이유 |
|---:|---|---|
| 1 | ζ | 작고 확실한 bench correction |
| 2 | γ 재측정/report artifact | AutoScraper 는 board-shape + real seed 로 다시 봐야 함 |
| 3 | β timebox spike | field mapping 문제에 직접 대응. production 전 spike |
| 4 | θ signal-only 조사 | hint 수준이면 risk 낮음 |
| 5 | δ offline prototype | register path 전 sitemap URL hit-rate 측정 |
| 6 | ε bench-only | port 후 matrix cell 만들기 전 통합 금지 |
| 7 | α offline evidence | prompt 미포함으로 relevance 만 측정 |
| 8 | η | 자동 retry 금지. 안내 message 실험부터 |

ζ > α 는 합리적이다.

하지만 ζ는 새 production layer 가 아니라 bench correction 이다.

---

## 8. plan 의 큰 누락

| 누락 | 영향 |
|---|---|
| test plan 없음 | 기존 easy site regression 방지 불가 |
| rollback 전략 없음 | prompt/digest schema 변경 후 실패 기준 없음 |
| A/B 측정 방법 없음 | 후보 추가가 LLM 선택률을 올리는지 모름 |
| prompt token budget 없음 | α/ε 후보 추가 비용 미계산 |
| timeout budget 없음 | δ/η register 단계 비용 미계산 |
| artifact schema migration 없음 | source/lastmod/candidate 추가 시 contract 필요 |
| false-positive taxonomy 없음 | wrong-block 후보 label/drop 기준 없음 |

최소 fixture set:

| class | fixture |
|---|---|
| easy static | `skku_cse` |
| wrong widget | `gamemeca` |
| nav/login shell | `naver_cafe_gutterlife` |
| pagination | `arca_trickcal` |
| SPA/API | `nexon_bluearchive` |
| sitemap gate | board-shape reject 신규 batch 필요 |

---

## 9. 즉시 진행 권장 vs 더 측정 필요 bucket

즉시 진행 권장:

| 후보 | 범위 |
|---|---|
| ζ | `mdr_guarded_bench.py` bench fix + rerun only |
| γ | production 통합 말고 board-shape failed + real post seed 재측정 |
| lastmod | observe-only artifact 설계 검토. polling 변경 금지 |

더 측정 필요:

| 후보 | 필요한 측정 |
|---|---|
| α | prompt 에 넣지 말고 offline candidate relevance score 먼저 |
| ε | Py3 port 후 matrix row. 통합 전 |
| β | 1-2일 spike 로 field mapping 성공률 측정 |
| δ | sitemap top URL 이 실제 article 인 비율 측정 |
| θ | canva/salesforce 외 같은 pattern 2-3건 수집 |

보류/금지:

| 후보 | 이유 |
|---|---|
| η 자동 retry | gate-bench in-scope 0. prod 오염 risk |
| α production merge | v2 결론 “MDR drop” 과 충돌 |
| ε production merge | bench 없음 |
| δ register path 직접 결합 | timeout/regression risk |

최종 메모:

plan 은 layer inventory 로는 유용하다.

하지만 “작은 port 비용” 을 “양의 EV” 로 너무 빨리 환산한다.

현재 증거가 지지하는 것은 새 layer 추가가 아니라, 실패 후보를 더 잘 거르고 재측정하는 작은 실험들이다.
