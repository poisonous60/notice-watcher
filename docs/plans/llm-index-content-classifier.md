# 구현 계획 — LLM index/content 분류기로 게이트 false-reject 봉합

## 0. 배경·근거 (PoC 검증 완료)

게시판(board=index) vs 단일글(article=content) 판정을 현재는 `scripts/register.py` 의 5개 휴리스틱 게이트가 `return 3`(rc=3 gate_reject)으로 *hard-reject* 한다. 사이트 다양성 때문에 게이트마다 사이트별 escape 주석이 누적(주먹구구), 매 batch 새 false-reject 발생.

학계 근거: index page vs content page 분류는 LLM 으로 F1 0.89 / precision 0.98 (arXiv 2505.06972, GPT-4o, title+body 입력). 휴리스틱 baseline 천장은 F1 0.78.

**PoC 실측** (`scripts/_exp_classify_clean.py`, gemini-2.5-flash, trafilatura 본문추출):
- board recall(=false-reject 안 함) **19/21 = 0.905**
- article precision(=article 정확 거부) **6/6 = 1.000**
- overall acc 0.926 — arxiv 재현.
- 잔여 2 miss = 둘 다 SPA(정적 HTML 이 단일글처럼 보임). **현 board_shape 도 어차피 거부할 케이스** → LLM 이 엄격히 우월, regression 없음.

## 0b. codex 리뷰 반영 (BLOCKER 해소)

- **classifier 입력 HTML = `digest["list_html"]["source"]` 의 raw 파일** (PoC 가 검증한 바로 그 바이트). `digest["list_html"]["html"]` 은 `clean_html()` 200KB cap + script/meta strip → SPA(discuss.python/django)에서 body=0·title='' 로 무너짐을 실측 확인. source 읽기 실패 시 cleaned `html` fallback, 그것도 비면 `class="?"`.
- **`--gate-only` 모드는 veto 전면 skip** — "LLM 0콜 보장" 유지. 헬퍼가 `args.gate_only` 받아 즉시 거부(현 rc=3/6) 보존.
- **classifier 결과는 register 호출당 1회 memoize** — `_root_marketing_homepage_check` 가 내부에서 `_board_shape_check` 호출 + override 후 later 게이트 재진입 → 다중 콜 방지. `(slug,url)` 키 로컬 캐시.
- **veto 는 반드시 `_save_rejected` *전*** 실행 — override 시 마커/learn 미발생(게이트는 이미 `learn=False` → blacklist 안 씀, orphan 없음).
- routing fallback 정정: 코드 기본값은 `GEMINI_MODEL` env 또는 하드코딩 `gemini-2.5-flash`(flash-lite 아님) — gitignore 된 `output/llm_routing.json` 무관하게 안전.

## 1. 설계 — "게이트 veto" (replace 아님)

5개 구조 게이트(`_single_article_nav_only_check`·`_meta_article_diverging_check`·`_multi_host_hub_check`·`_root_marketing_homepage_check`·`_board_shape_check`)는 **그대로 둔다** — 단, 거부 직전에 LLM 분류기를 호출해 **veto** 한다:

- 게이트가 거부하려 함 → `classify_index_content(digest, url)` 호출
- 결과 `index`(conf ≥ threshold) → **거부 취소**, override 로그 남기고 일반 파이프라인 계속
- 결과 `content` → 기존대로 거부(rc=3), REJECTED 마커에 분류기 사유 추가
- 분류기 호출 실패(quota/parse) → **현 동작 유지(거부)** = fail-safe, 신규 리스크 0

**veto 인 이유**: 게이트는 "LLM 콜을 언제 쓸지" 정하는 싼 pre-filter 로 유지(통과 케이스는 어차피 generation LLM 콜 → 증분 없음, would-be-reject 만 +1콜). 외과적·되돌리기 쉬움.

**hard-reject 유지(veto 안 함)**: `recognize_reject`(host 명시 known-article PATTERNS) + capability_blocked(rc=5 captcha). 고정밀·false-reject 원인 아님.

## 2. 변경 파일

1. **requirements.txt** += `trafilatura>=2.0` (courlan·htmldate 딸려옴). N100 배포 시 `pip install -r requirements.txt` 필요(CLAUDE.md §2 step 5).
2. **generate/classify.py** (신규):
   ```python
   def classify_index_content(*, url: str, digest: dict, client=None) -> dict:
       # html = read(digest["list_html"]["source"])  # raw 파일 (PoC 입력)
       #        fallback: digest["list_html"]["html"] (cleaned) → 둘 다 없으면 class="?"
       # trafilatura.bare_extraction(html, favor_recall=True) → title+body[:2000]
       # struct hint = digest["list_candidates"] 의 same-host 반복 글-행 수 / feed 수 / SPA flag
       # client_for("classify_index_content"); temperature=0 (명시 전달); json_mode
       # transient(503/429) retry; return {"class":"index"|"content"|"?","confidence":float,"reason":str}
       # 실패/parse_fail → {"class":"?"} (caller 가 거부 유지 = fail-safe)
   ```
3. **prompts/classify.system.txt** + **prompts/classify.user_skeleton.txt** — 기존 prompt 파일 컨벤션(generate/prompts.py render_prompt) 따름. system = index/content 정의 + JSON 출력 스펙. user = URL/title/struct/body 슬롯.
4. **scripts/register.py**:
   - 헬퍼 `_classify_gate_veto(digest, url, gate_name, gate_msg) -> bool` — True=override(거부취소), False=거부유지.
   - 5개 게이트의 `return 3` 블록을 이 헬퍼 경유로. override 시 `[register] 🔵 gate <name> 거부를 LLM 분류기가 board(index)로 판단 — 거부 취소` 로그.
   - REJECTED 마커 사유에 분류기 verdict+reason append.
5. **output/llm_routing.json**: `"classify_index_content": "gemini:gemini-2.5-flash"` 엔트리 추가(없으면 `_default` = 현재 gemini-3.1-flash-lite 로 fallback — flash-lite 적정성 미검증이라 명시 라우팅 권장). *주의*: routing.json 은 output/(gitignore) — 코드 정확성이 이 파일에 의존하면 안 됨. 코드 기본값은 `_fallback_default()`(gemini 기본 모델)로 동작하되, flash 권장을 docs 에 명시.
6. **tests/**: `tests/classify/test_classify_index_content.py` — (a) classify 단위: fixture HTML(board·article) + mock client, prompt 조립·파싱·temperature=0 인자·실패 fallback("?"); (b) register 통합: `_classify_gate_veto` — override 시 마커 미생성·learn 미발생, content 시 마커 사유 append, 실패("?") 시 거부 유지, `--gate-only` veto skip, memoize 1회 콜, discourse early-return 이 classifier 우회.
7. **docs/adr/**: 새 ADR — 거부 정책을 *결정적 게이트* → *LLM-veto 게이트* 로 변경(deterministic→probabilistic) 기록. ADR 0003(자가개선) 계열.
8. **배포 순서**(CLAUDE.md §2): commit→push→pre-push hook→N100 `git pull --ff-only`→`pip install -r requirements.txt`(trafilatura 신규 — restart 전)→`systemctl --user restart notice-bot.service`(register.py 변경됨).

## 3. 파라미터 (PoC 기반)

- 본문추출: `favor_recall=True` (recall 0.905 달성; precision 모드는 2 SPA miss 못 살림 → 차이 없어 recall 유지).
- body cap 2000자 (arxiv 동일).
- threshold: class=="index" AND confidence ≥ **0.5** 에서 override (PoC 정답 board conf 0.8~0.95 분포, article precision 100% → 공격적 override 안전). 상수로 박고 주석.
- 모델: gemini-2.5-flash (PoC 검증). flash-lite 미검증.

## 4. 검증 (구현 후)

- 단위 테스트 green.
- `scripts/_exp_classify_clean.py` 재실행 — 회귀 없음 확인 후 삭제.
- **batch 재실행**: 과거 false-reject(forum roots) 가 이제 거부 안 되고 통과하는지 — `python scripts/register.py "<forum url>"` 몇 건으로 rc≠3 확인.
- pre-push hook(`probe_smoke --stage 3 --stage 5`) 통과.

## 5. 리스크·미해결 (codex 검토 요청 포인트)

- **false-accept 증가**: 게이트가 옳게 거부한 marketing-root 등을 분류기가 "index" 로 통과시킬 수 있음 → generation 헛돔. 단 사용자가 "확실히 게시판 아닌 것만 거부" 선호 명시 → 허용 tradeoff. generation 이 실패하면 graceful.
- **SPA(list_html 빈약)**: 정적 HTML 에 리스트 없으면 분류기도 약함(현재와 동일, regression 없음). 진짜 해법은 render — 별도 트랙.
- **비용/지연**: would-be-reject 당 +1 gemini 콜. 허용 범위로 판단.
- **routing 의 output/ 의존**: 코드 기본값으로 방어. flash 권장은 docs.
- **결정성**: temperature 0. 그래도 LLM 비결정 가능 — 동일 URL 재등록 시 다른 결과 가능성(낮음). 모니터링.
