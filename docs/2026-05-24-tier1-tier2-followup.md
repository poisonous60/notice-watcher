# 2026-05-24 — tier1/tier2 prior-art follow-up

2026-05-18 문서의 후속. 질문은 하나다.

LLM scraping 도구만 볼 게 아니라 MDR/REPS 같은 canonical 반복 추출 알고리즘과 RSS-builder 코드도 봤어야 했나?

입력 자료:

- [MDR 코드 검사 노트](../experiments/prior-art-bench/notes_code_inspect_mdr.md)
- [AutoScraper 코드 검사 노트](../experiments/prior-art-bench/notes_code_inspect_autoscraper.md)
- [REPS 코드 검사 노트](../experiments/prior-art-bench/notes_code_inspect_reps.md)
- [matrix.md](../experiments/prior-art-bench/matrix.md)
- [mdr_bench.py](../experiments/prior-art-bench/tools/mdr_bench.py)
- [mdr_list_candidates_py3.py](../experiments/prior-art-bench/tools/mdr_list_candidates_py3.py)
- [autoscraper_bench.py](../experiments/prior-art-bench/tools/autoscraper_bench.py)
- [2026-05-18 prior-art 조사](2026-05-18-prior-art-조사.md)

경로 검증:

| 경로 | 상태 | 메모 |
|---|---:|---|
| `generate/generator.py` | 존재 | 실제 config 생성 경로 |
| `generate/prompt.py` | 존재 | 실제 prompt assembly |
| `generate/config_writer.py` | 없음 | AutoScraper 노트가 path drift 로 표시 |
| `generate/list_candidates.py` | 없음 | 실제 후보 추출은 `probe/extract.py` |
| `probe/extract.py` | 존재 | 후보 추출 본체 |
| `probe/_heuristic.py` | 존재 | 실제 heuristic registry |
| `probe/heuristics.py` | 없음 | 실제는 `probe/_heuristic.py` |
| `experiments/prior-art-bench/notes_code_inspect_rss-proxy.md` | 없음 | rss-proxy 코드 검사 근거 없음 |

---

## 1. TL;DR

MDR: ★★. 정적 JSP 는 맞췄지만 gamemeca/naver/arca 에서 인기게임·상단 nav·pagination 을 골랐다. 구조 반복 신호는 가치 있으나 main-list 판별 신호가 부족하다.

AutoScraper: ★. seed 기반 triage assist 로만 가능. seed 는 `ground_truth[0]` 이고, rolling front page 에서는 seed 글이 이미 밀려났을 수 있다.

REPS: ★. tag-sequence 반복 prior-art 로 참고만. concrete CSS selector / field selector 를 만들지 못한다.

rss-proxy: ❌. 요청된 코드 검사 노트가 디스크에 없다. 이번 문서에서는 채택 근거도 반박 근거도 만들지 않는다.

---

## 2. Bench 결과

전체 매트릭스: [matrix.md](../experiments/prior-art-bench/matrix.md)

이번 후속의 직접 비교 행:

| row \ site | skku_cse | gamemeca | nexon_bluearchive | naver_cafe_gutterlife | arca_trickcal |
|---|---:|---:|---:|---:|---:|
| `manual_bs4` | R=1.00 / L=1.00 / 0.4s / n=11/10 | R=1.00 / L=1.00 / 1.4s / n=15/10 | R=0.00 / L=0.00 / 0.7s / n=0/10 | R=1.00 / L=1.00 / 0.9s / n=10/10 | R=0.00 / L=0.00 / 0.7s / n=20/10 |
| `crawl4ai_llm` | R=1.00 / 17.0s | R=1.00 / 19.4s | R=0.00 / 6.7s | R=1.00 / 11.5s | R=0.20 / 131.9s |
| `llm_scraper` | R=1.00 / 15.7s | R=1.00 / 25.4s | R=1.00 / 20.0s | R=1.00 / 11.2s | R=0.70 / 53.3s |
| `firecrawl_json` | R=1.00 / 54.6s | R=1.00 / 16.8s | R=0.70 / 21.7s | R=1.00 / 23.3s | R=0.00 / 13.9s |
| `mdr_unsupervised` | R=1.00 / L=1.00 / 0.3s / n=10/10 | R=0.00 / L=0.00 / 0.7s / n=10/10 | R=0.00 / L=0.00 / 0.4s / n=0/10 | R=0.00 / L=0.00 / 0.4s / n=7/10 | R=0.00 / L=0.00 / 0.4s / n=10/10 |
| `autoscraper_seeded` | R=0.00 / L=0.00 / 0.1s / n=10/10 | R=0.00 / L=0.00 / 0.1s / n=0/10 | R=0.00 / L=0.00 / 0.0s / n=0/10 | R=0.00 / L=0.00 / 0.0s / n=1/10 | R=0.00 / L=0.00 / 0.1s / n=0/10 |

MDR bench 의 범위:

| 항목 | 내용 |
|---|---|
| 사용 | `MDR.list_candidates` 의 Py3 port |
| 제외 | full record alignment / numpy / scipy / C extension |
| 후처리 | container 선택 후 direct child 를 row 로 보고 첫 `<a>` 추출 |
| 근거 | [mdr_bench.py](../experiments/prior-art-bench/tools/mdr_bench.py) 주석 |

MDR 실패 양상:

| 사이트 | MDR 결과 | 해석 |
|---|---|---|
| skku_cse | R=1.00 | 정적 JSP board 반복 DOM 에서는 충분 |
| gamemeca | R=0.00, n=10 | 뉴스 목록 대신 인기게임 container 선택 |
| naver_cafe | R=0.00, n=7 | 게시글 대신 top nav 선택 |
| arca_trickcal | R=0.00, n=10 | 게시글 대신 pagination 숫자 선택 |
| nexon_bluearchive | R=0.00, n=0 | static HTML 에 row 없음 |

gamemeca 는 "리그 오브 레전드", "리니지", "발로란트" 같은 game link 를 추출했다.

이것이 말하는 것:

| 관찰 | 의미 |
|---|---|
| 인기게임 widget 도 반복 구조 + link density 가 높음 | MDR 는 "record-like" 를 찾지 "news-list" 를 고르지 않음 |
| naver top nav 도 반복 anchor 집합 | semantic guard 없이 nav false-positive 발생 |
| arca pagination 도 깨끗한 반복 구조 | 숫자-only pagination reject 규칙은 MDR 밖의 domain guard |

AutoScraper bench 의 seed:

| 항목 | 내용 |
|---|---|
| seed source | `ground_truth/<slug>.json` 의 `posts[0]` |
| 코드 근거 | [autoscraper_bench.py](../experiments/prior-art-bench/tools/autoscraper_bench.py) 의 `_load_seed` |
| 의미 | 사용자가 "보이는 제목 하나" 를 주는 상황을 흉내 |
| score 의미 | seed 하나로 다른 GT row 를 얼마나 회복했는가 |

AutoScraper 결과 해석:

| 사이트 | 결과 | 해석 |
|---|---:|---|
| skku_cse | R=0.00, n=10 | title 은 잡았지만 URL 없음. config 로 못 씀 |
| gamemeca | R=0.00, n=0 | seed 가 없거나 rule overfit |
| nexon_bluearchive | R=0.00, n=0 | static HTML 에 seed row 없음 |
| naver_cafe | R=0.00, n=1 | seed 1개만 회수 |
| arca_trickcal | R=0.00, n=0 | seed 가 없거나 rule overfit |

rolling-front-page 주의:

- gamemeca, arca 는 front page 가 빠르게 바뀐다.
- seed 가 `ground_truth[0]` 이어도 fetch 시점에 그 글이 이미 밀려났을 수 있다.
- 이 경우 `n_rules=0`, `n_titles=0` 은 bug 라기보다 seed 기반 scraping 의 본질적 한계다.
- 사용자가 붙여준 제목도 현재 DOM 에 없으면 학습할 수 없다.

---

## 3. 각 도구 verdict

### ★★ MDR

판정: adopt after one more check.

정확히는 production 도입이 아니라 bounded extra signal bench 다.

| 항목 | 근거 |
|---|---|
| 실제 후보 추출 위치 | `probe/extract.py:54-114` (`notes_code_inspect_mdr.md:11`) |
| path drift | `generate/list_candidates.py` 없음 (`notes_code_inspect_mdr.md:11`) |
| heuristic registry drift | `probe/heuristics.py` 없음, 실제는 `probe/_heuristic.py` (`notes_code_inspect_mdr.md:12`) |
| replacement 부정 | "MDR should not replace..." (`notes_code_inspect_mdr.md:306`) |
| augmentation 가능 | top-K HTML candidates extra signal (`notes_code_inspect_mdr.md:307`) |
| 구조 신호 | clustered tree match / partial alignment (`notes_code_inspect_mdr.md:316`) |

실제 경로:

| cited path | 상태 |
|---|---:|
| `probe/extract.py` | 존재 |
| `probe/_heuristic.py` | 존재 |
| `generate/list_candidates.py` | 없음 — [경고: 해당 경로 없음. `probe/extract.py` 확인 필요] |
| `probe/heuristics.py` | 없음 — [경고: 해당 경로 없음. `probe/_heuristic.py` 확인 필요] |

통합 지점:

| 후보 | 판단 |
|---|---|
| `probe/extract.py` replacement | 하지 말 것 |
| `scripts/probe.py` Phase 7 후 extra evidence | 가능 |
| `write_list_candidates` 에 `mdr_score` 류 추가 | bench 후 가능 |
| runtime engine dependency | 하지 말 것 |

왜 ★★ 인가:

- canonical 구조 반복 신호는 있다.
- matrix 에서는 5개 중 1개만 성공했다.
- 실패가 nav/widget/pagination false-positive 로 설명된다.
- 따라서 main selector 로 채택하면 손해다.
- 단, top-K 후보의 structural confidence 로는 아직 확인 가치가 있다.

### ★ AutoScraper

판정: reference only.

단, `/watch` 실패 후 "사용자가 보이는 제목 하나를 붙여줌" 흐름의 triage assist 로는 남길 수 있다.

| 항목 | 근거 |
|---|---|
| 알고리즘 성격 | "seeded DOM-path learner, not a notice-board row model" (`notes_code_inspect_autoscraper.md:38`) |
| 없는 경로 | `generate/config_writer.py`, `generate/list_candidates.py` 없음 (`notes_code_inspect_autoscraper.md:26-31`) |
| 실제 생성 경로 | `generate/generator.py` + `generate/prompt.py` (`notes_code_inspect_autoscraper.md:28-31`) |
| `/watch` 삽입 후보 | `bot/worker.py:371-375` (`notes_code_inspect_autoscraper.md:216`) |
| translation 한계 | "not lossless" (`notes_code_inspect_autoscraper.md:331`) |
| verdict | experimental failover / triage assist only (`notes_code_inspect_autoscraper.md:409-411`) |

실제 경로:

| cited path | 상태 |
|---|---:|
| `generate/generator.py` | 존재 |
| `generate/prompt.py` | 존재 |
| `generate/config_writer.py` | 없음 — [경고: 해당 경로 없음] |
| `generate/list_candidates.py` | 없음 — [경고: 해당 경로 없음. `probe/extract.py` 확인 필요] |
| `bot/worker.py` | 존재 |
| `probe/extract.py` | 존재 |

통합 지점:

| 후보 | 판단 |
|---|---|
| `/watch` rc=1 실패 후 seed prompt | 가능하지만 UX/persistence 비용 큼 |
| `/report` owner triage | 더 적합 |
| config_writer replacement | 부적합 |
| 자동 config write | 부적합 |

왜 ★ 인가:

- matrix 에서 list recall 은 전부 0.00.
- skku_cse 는 title 10개를 얻었지만 URL 0 이다.
- rolling site 는 seed 가 사라지면 학습 자체가 불가능하다.
- 그래도 "정확한 제목이 DOM 어디에 있나" 를 찾는 triage helper 로는 설명 가능하다.

### ★ REPS

판정: reference only.

| 항목 | 근거 |
|---|---|
| fit section | REPS 노트 §4 (`notes_code_inspect_reps.md:146`) |
| missing requested path | `generate/list_candidates.py` 없음 (`notes_code_inspect_reps.md:148`) |
| missing requested path | `probe/heuristics.py` 없음 (`notes_code_inspect_reps.md:150`) |
| selector 부재 | concrete selector string 을 반환하지 않음 (`notes_code_inspect_reps.md:170`) |
| config replacement 불가 | `skku_cse_1582.json` 형태에 drop-in 아님 (`notes_code_inspect_reps.md:172`) |
| verdict | reference-only (`notes_code_inspect_reps.md:253-255`) |

실제 경로:

| cited path | 상태 |
|---|---:|
| `generate/list_candidates.py` | 없음 — [경고: 해당 경로 없음. `probe/extract.py` 확인 필요] |
| `probe/heuristics.py` | 없음 — [경고: 해당 경로 없음. `probe/_heuristic.py` 확인 필요] |
| `configs/skku_cse_1582.json` | 존재 |

왜 ★ 인가:

- REPS 는 MDR 보다 단순하다.
- output 이 `Unit` 객체 / tag pattern 이라 config schema 에 바로 연결되지 않는다.
- selector synthesizer 를 새로 만들면 비용이 커진다.
- 발표/문서에서 wrapper-induction prior-art 로 언급하면 충분하다.

### ❌ rss-proxy

판정: drop from current action.

| 항목 | 상태 |
|---|---|
| 요청 입력 파일 | `experiments/prior-art-bench/notes_code_inspect_rss-proxy.md` |
| 실제 디스크 존재 | 없음 |
| 대체 파일명 | `notes_code_inspect_rss_proxy.md` 도 없음 |
| 코드 검사 근거 | 없음 |

이번 문서에서 결론낼 수 있는 것:

- rss-proxy 류를 채택하자고 말할 근거가 없다.
- rss-proxy 류를 기술적으로 반박할 근거도 없다.
- 2026-05-18 문서의 FetchRSS 평가는 "selector 손-박기 강제라 자동성 비교 의미 낮음" 수준에 머문다.

---

## 4. 5월 18일 문서가 놓쳤던 점

사용자 우려에 대한 답:

| 대상 | 5월 18일 누락 여부 | 이번 후속 판단 |
|---|---:|---|
| MDR | 맞음 | 봤어야 했다. 다만 replacement 아님 |
| REPS | 맞음 | 봤어야 했다. 다만 reference only |
| AutoScraper | 부분 | 논문 언급은 있었지만 실제 코드/bench 는 부족했다 |
| RSS-builder code | 맞음 | 이번 입력에도 코드 검사 노트가 없어 아직 결론 없음 |

MDR 를 봐서 새로 알게 된 점:

| 확인 | 판단 |
|---|---|
| 반복 DOM 구조 신호 | 실제로 있음 |
| CSS selector 직접 출력 | 없음 |
| title/date/url/post_id field 선택 | 없음 |
| main list semantic | 없음. matrix 에서 widget/nav/pagination 선택 |
| 우리 후보 생성과 관계 | replacement 가 아니라 extra evidence 후보 |

REPS 를 봐서 새로 알게 된 점:

| 확인 | 판단 |
|---|---|
| tag-name contiguous sequence counting | prior-art 로 의미 있음 |
| BeautifulSoup `Unit` 반환 | 사람이 inspect 하기엔 가능 |
| concrete CSS selector | 없음 |
| Python 2 drift | port 비용 있음 |

AutoScraper 를 봐서 새로 알게 된 점:

| 기존 기대 | 이번 확인 |
|---|---|
| 한 제목 seed 로 config 생성 가능 | 과장. DOM path 후보 정도 |
| `/watch` 실패 복구 | rc=1 일부 triage assist 가능 |
| 자동 등록 대체 | 불가 |
| seed 안정성 | rolling front page 에 취약 |

RSS-builder code:

| 항목 | 결론 |
|---|---|
| 이번 입력 파일 | 없음 |
| 외부 검색 | 하지 않음 |
| 결론 | 보류 |

따라서 5월 18일 문서는 "시장 도구와 LLM 도구" 는 봤지만 "후보 생성 알고리즘 prior-art" 는 부족했다.

다만 이번 후속까지 포함한 결론은 더 보수적이다.

반복 단위 발견만으로는 부족하다. 우리 문제는 stable selector + field extraction + polling config 생성이다.

---

## 5. 다음 step 후보 (ranked)

우선순위는 "실제 worth touching" 기준.

| # | 작업 | 효과 | 비용 |
|---:|---|---|---|
| 1 | **MDR vs `probe/extract.py` 3번째 bench row** | 지금 결론의 핵심 공백 제거. 기존 heuristic 과 MDR 를 head-to-head 비교 | 0.5~1일. 저장 HTML fixture 로만 |
| 2 | **MDR top-K 보조 점수 실험** | nav/pagination false-positive 를 줄일 수 있는지 확인 | 1~2일. 성공 시 prompt evidence 필드 후보 |
| 3 | **AutoScraper seed triage offline script** | `/watch` rc=1 실패 중 "사용자가 제목 하나 제공" 케이스 확인 | 0.5~1일. config 자동 write 금지 |
| 4 | **REPS 는 문헌/용어 참고로만 정리** | wrapper-induction 설명 보강 | 0.5일 문서 작업 |
| 5 | **RSS-builder 코드 조사 재실행** | 5월 18일 누락분 중 남은 공백 해소 | 0.5~1일. 실제 소스/노트 확보 후 가능 |
| 6 | **Firecrawl `/map` 검토 유지** | 5월 18일의 가장 실용적인 next-action. 이번 결과와 충돌 없음 | 1~2일 |

현실적인 선택:

| 후보 | 지금 만질 가치 |
|---|---|
| MDR | 있음. 단 replacement 가 아니라 bench/보조 신호 |
| AutoScraper | 낮음. seed UX 까지 포함하면 비용 커짐 |
| REPS | 낮음. selector synthesis 없이는 도입 가치 작음 |
| rss-proxy | 현재 없음. 노트/소스 확보 전까지 action 불가 |

---

## 6. 본 조사가 결론짓지 않은 것

본 조사가 결론짓지 않은 것:

- `probe/extract.py` heuristic 이 MDR 보다 낫다는 것.
- MDR 이 `probe/extract.py` heuristic 보다 낫다는 것.
- 둘의 직접 비교는 아직 없다. 이를 보려면 `probe/extract.py` 기반 3번째 bench row 가 필요하다.
- full MDR alignment 까지 붙였을 때 결과가 좋아지는지 여부.
- MDR false-positive 를 URL pattern / nav guard / pagination guard 로 얼마나 줄일 수 있는지.
- AutoScraper 가 실제 Discord multi-turn UX 에서 사용자가 제공한 seed 로 얼마나 회복하는지.
- AutoScraper seed 가 rolling-front-page 에서 얼마나 자주 사라지는지.
- REPS 에 selector synthesizer 를 붙이면 쓸 만해지는지.
- rss-proxy / RSSHub / RSS-builder 계열 코드가 자동 selector 생성에 도움이 되는지.
- production 등록률이 오르는지. 이번 문서는 production code 를 수정하지 않았고 bench 를 새로 돌리지 않았다.

Negative scope:

| 범위 | 상태 |
|---|---|
| production code 수정 | 안 함 |
| benchmark 재실행 | 안 함 |
| N100 배포 | 안 함 |
| `generate/`, `probe/`, `bot/`, `engine/` 수정 | 안 함 |
| 외부 검색 | 안 함 |
| 없는 경로 silently propagate | 안 함. `generate/list_candidates.py`, `generate/config_writer.py`, `probe/heuristics.py`, rss-proxy 노트 부재를 명시 |

