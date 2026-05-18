# 2026-05-18 — prior-art follow-up 계획 v2 (codex 리뷰 반영)

상위 문서 [docs/2026-05-18-prior-art-조사.md](2026-05-18-prior-art-조사.md) §6 의
잠재 next-action 1~5 를 *실행 가능 단위* 로 분해.

**v2 변경 사항** (codex rescue 리뷰 14건 반영, 2026-05-18):
- #3 schema 충돌 정정 (기존 `article.content` chain 깨지 X — 새 source kind 또는 별도 키)
- #3 status skip 중복 제거 (기존 `article.skip_status` 재사용, `response_branch_body` = JSON field branch 한정)
- #3 source 문법 = 기존 `{"from":"json","path":[...]}` 재사용
- #3 reviewer rubric = 이미 9~12 존재 — 검증 출력 첨부 의무로 정정
- #1 통합 위치 = `scripts/register.py` (post-probe) 확정. `bot/url_gate.py` 손대지 X
- #1 env = `deploy/.env.example` + `bot/config.py firecrawl_api_key()` accessor
- #1 N100 배포 단계 추가, cost telemetry 추가
- #4 selector breakage 축 drop, recall + latency 축만 유지
- #5 조기 중단 조건 + jitter + #3 의존 완화 (실험만, prod commit 만 #3 후)
- #2 효과 = `cf_fingerprint_hide_required` 후보 생성 중심으로 낮춤
- §7 Firecrawl key 확인 = Phase B 시작 전

## 0. 의도·범위

- 조사 결론(§6 표 #1~5)을 **실행** 으로 옮김. #6(슬라이드) 제외.
- 각 action 의 **deliverable / success criterion / rollback** 명시 — CLAUDE.md §4 준수.

## 1. 의존·순서 (v2)

| # | action | 의존 | 독립 가능? |
|---|---|---|---|
| 1 | Firecrawl `/map` 통합 (`scripts/register.py` post-probe) | env 확보 | ✅ |
| 2 | ArcaLive case .md backfill | (없음) | ✅ |
| 3 | `response_branch_body` 어휘 박기 | (없음. 트리거 이미 도달; #2 = 권장) | ✅ |
| 4 | llm-scraper `generate()` 비교 bench (재설계) | (없음) | ✅ |
| 5 | stealth 강도 점검 (실험만) | (없음). prod commit 만 #3 후 | ✅ |

### 권장 phase (v2 — 의존 완화)

- **Phase A (직렬, 1.5일)** — #2 → #3
  - #2 는 0.5일. #3 의 evidence 강화 + ADR backfill 마무리.
  - #3 = vocab-ext SKILL **첫 dogfood**. engine/schema/prompt 변경 → 안전망 필요.
- **Phase B (병렬 OK, 2~3일)** — #1, #4, #5
  - #1 = `scripts/register.py` post-probe + 신규 `engine/url_discovery.py`. 파일 겹침 X.
  - #4 = `experiments/register-compare-bench/`. 영향 X.
  - #5 = `experiments/arca-stealth-bench/`. prod adapter 안 건드림 (실험만).

---

## 2. Action #2 — ArcaLive case .md 생성 (0.5일)

### 현재 상태
- 4 handwritten 어댑터 중 ArcaLive 만 case .md 없음.
- `python scripts/cases_index.py vocab-trigger --json` 출력 = `response_branch_body` 3 cases 이미 트리거.
  ArcaLive 추가 = +1 evidence (필수 X).
- bench evidence: `experiments/prior-art-bench/results/llm_scraper/arca_trickcal__run*.json` (0.70 / 53s)
  + `experiments/prior-art-bench/results/crawl4ai_llm/arca_trickcal__run*.json` (0.20 / 132s).

### Deliverable (v2 — 범위 축소)
- `docs/cases/arca-live_trickcal_6703bf64.md` 신규 (slug = config 파일명).
- frontmatter `vocab_candidates`:
  - **주축**: `cf_fingerprint_hide_required` (high) — bench evidence (crawl4ai 0.00 vs llm_scraper 0.70).
    `adapters/arca.py` 의 playwright-stealth 사용 근거.
  - **부축**: `response_branch_body` — **해당 없음 근거 명시** (`adapters/arca.py` 본문 분기 없음 → 후보 추가 X).
- `python scripts/cases_index.py` 호출 → INDEX.md 갱신.

### Success criterion (v2 — 낮춤)
- `cases_index.py` INDEX 에 ArcaLive 행 추가
- `vocab-trigger --json` 의 sub_threshold 또는 triggered 에 `cf_fingerprint_hide_required` 등장 (1건)
- `response_branch_body` 카운트는 *변동 없음* (ArcaLive 후보 추가 X 명시 ↔ 부풀리지 않음)

### Rollback
- case .md 1개 삭제 + INDEX.md 재생성. 무비용.

---

## 3. Action #3 — `response_branch_body` 어휘 박기 (vocab-ext 첫 dogfood, 1.5일 + reviewer)

### 현재 상태
- 트리거 카운트 3 (`vocab-trigger --json` 확인). 임계 이미 도달.
- 3 cases 패턴:
  - **NaverCafe / DaumCafe**: 401/403 → 본문 비움 — **이미 `article.skip_status: [401,403]` 으로 표현 가능**
    (codex 지적 #2). → 이 부분은 *새 어휘 불필요*. case .md 의 reasoning 정정 + reviewer 가 reuse 명시 확인.
  - **Reddit**: 응답 type field (`data.kind == "t3"`) 기준 분기 (self / 이미지 / 갤러리 / 링크 4종) →
    **여기가 진짜 `response_branch_body` scope**.

### v2 — schema design (codex MAJOR 1~3 반영)
- 기존 `article.content` = source dict 의 chain (fallback). **chain 깨지 X**.
- **새 source kind 추가** = `{"from": "branch", "when": {...}, "source": {...}}`:
  - chain 안에서 평가 — `when` 매칭 시 그 `source` 평가, 안 매칭 시 다음 chain item.
  - `when.field_eq: {path: ["data","kind"], value: "t3"}` — JSON field 평가 (status_in 은 안 넣음 — `skip_status` 재사용).
  - `source` = 기존 source 형식 그대로 (`{"from":"json","path":["data","selftext_html"]}` 등). dot-string 사용 X (codex MAJOR 3).
- scope 한정: **JSON field branch 만**. status 분기 = 기존 `article.skip_status` (codex MAJOR 2).

### Deliverable
- `engine/extract_helpers.py` — `from:"branch"` source kind 평가 함수 추가.
- `engine/config_schema.py` — `validate_config` 에 branch source 검증 룰 (when.path 배열 / when.field_eq.value 존재 등).
- `prompts/config_writer.system.txt` — `from:"branch"` 어휘 토큰 *추가* (수정 X, fix-layer A).
- `generate/prompt.py` `_EXAMPLE_CONFIG_FILES` — Reddit 케이스 1개 예제 추가 (fix-layer B).
- `tests/engine/test_branch_source.py` — fixture 3개 (Reddit self / 이미지 / 갤러리 응답 mock).

### Success criterion (v2 — codex MINOR 1 반영: 같은 strategy 전체 회귀)
1. `python scripts/probe_smoke.py` 그린
2. `configs/*.json` **전체** `validate_config()` 통과 — backward compat (새 source kind = 선택)
3. **같은 strategy (`handwritten`) 사이트 모두 회귀** — `register.py --config <slug>` 결과 baseline 동등/개선
   - `adapters/arca.py`·`daumcafe.py`·`naver_cafe.py`·`reddit.py` 등 모든 handwritten 영향 확인
   - `httpx_json` / `httpx_html` / `playwright_html` 도 fetch_list 1건 sanity
4. **Gemini 토큰 비용 telemetry** (v2 신규) — prompt diff byte 수 + 신규 prompt 첫 run token count 기록
5. **reviewer subagent** (`hand-config-reviewer`) PASS — rubric 9~12 이미 `.claude/agents/hand-config-reviewer.md` 에 존재.
   main thread 가 prompt 에 *§5 결과 (1~4) 출력 첨부 의무* — 첨부 없으면 FAIL (codex NIT 반영).
6. case .md `vocab_candidates` 항목에 `applied: <commit_sha>` 추가

### Rollback
- 영향 config `.bak` 복구 (박기 직전 자동 백업)
- 영향 case .md 에 `vocab_attempt_failed: true` + `failure_reason` 박음 → 다음 호출 자동 강등

### v2 미정 결정 (단순화)
- (a) handwritten adapter → config 전환 = **본 작업 scope 외**. engine 어휘만 추가. config 전환은 별 작업.
- (b) migration script = **불필요** — 새 source kind = chain 안 추가 → backward compat (codex MAJOR 1 의 결과).
- (c) ~reviewer rubric 추가~ → **이미 존재** (`.claude/agents/hand-config-reviewer.md` line 76~). 검증 출력 첨부만 의무화.

---

## 4. Action #1 — Firecrawl `/map` 통합 (1~2일, v2 — 통합 위치 확정)

### 현재 상태
- bench 라이브: skku_cse → 15 entry (`/cse/notice.do` ✅), gamemeca → 11 entry, naver_cafe → 1 (한계).
- `scripts/register.py` 가 probe 호출 — post-probe 실패 시 `/map` fallback **자연스러운 자리** (codex MAJOR 4).
- `bot/url_gate.py` = 정책·SSRF 게이트 — **손대지 X** (책임 분리).

### Deliverable (v2)
- `engine/url_discovery.py` 신규:
  - `discover_board_candidates(url, api_key) -> list[str]` — `/map` (raw httpx POST) + sitemap entry
  - timeout 10s, fail-soft (`return []` if API fail or no key)
- `bot/config.py` 에 `firecrawl_api_key()` accessor 추가 (codex MAJOR 5).
- `deploy/.env.example` 에 `FIRECRAWL_API_KEY` 추가 (codex MAJOR 5 — `bot/.env.example` *없음* 확인).
- `scripts/register.py` — probe 결과 `failure_keys: [posts_nonempty]` 일 때 `/map` 호출 → `config_writer` retry prompt 에
  "다음 후보 중 board page 골라" 추가 → 1회 retry. 키 미설정 시 기능 비활성 (no-op).
- `output/firecrawl_map_log.json` — 호출별 (URL, 후보 수, 선택, credit, latency) 로그 (cost telemetry, codex MINOR 4).

### Success criterion
1. 합성 케이스: `register.py https://cse.skku.edu/` → `/cse/notice.do` 자동 등록 성공 (1 credit)
2. `pytest tests/engine/test_url_discovery.py` 그린 (httpx mock)
3. credit 사용량 < 5 (전체 test) — quota 관리
4. **N100 배포 확인** (v2, codex MINOR 3) — `git push` → N100 `git pull` + bot restart → key 미설정 시 disabled 확인

### Rollback
- `engine/url_discovery.py` 삭제 + `scripts/register.py`·`bot/config.py`·`deploy/.env.example` revert. 무비용.

### 미정 결정
- self-host vs hosted — hosted free tier (500 credit/월) 로 14 사이트 prod 충분. 등록 시점 1회 호출.

---

## 5. Action #4 — llm-scraper `generate()` 비교 bench (재설계, 0.5일)

### v2 변경 (codex MAJOR 6 — selector breakage 측정 불가 인정)
- **drop**: selector breakage 축 (10회 폴링 시간으로 측정 불가, 주 단위 폴링 필요)
- **유지**: recall (1회 GT 매칭) + latency (1회 폴링)
- **추가**: playwright 필요 여부 (engine vocab 으로 표현 가능한가?)

### Deliverable
- `experiments/register-compare-bench/` 신규:
  - `targets.json` — 3 사이트 (skku_cse, gamemeca, nexon_bluearchive)
  - `tools/our_register.py` — `python scripts/register.py --config-only --no-deploy <url>` → config JSON 보관
  - `tools/llm_scraper_generate.ts` — `scraper.generate(page, schema)` → script 보관
  - `run_polling.py` — 각 결과물 1회 폴링 → recall + latency
  - `README.md` — 결론 3~5줄 (어느 게 vocab-fit / 어느 게 자유도 필요)

### Success criterion
- 3 사이트 × 2 결과물 = 6 cell 완료
- `experiments/register-compare-bench/matrix.md` 생성
- 결론: "X 사이트 = 우리 vocab 충분 / Y 사이트 = playwright script 자유도 필요" 명시

### Rollback
- 폴더 통째 삭제. 무비용.

### v2 미정 (단순화)
- 비교 의미 = trade-off 표시 (apple vs orange OK). 결정은 사용자.

---

## 6. Action #5 — stealth 강도 점검 (0.5일 + 변동성, v2 — 조기 중단 추가)

### 현재 상태
- bench: arca.live 가 naive playwright + 3 옵션으로 70% 통과.
- prod `adapters/arca.py` = playwright-stealth 풀 패키지. *과한 방어* 가능성.

### Deliverable (v2)
- `experiments/arca-stealth-bench/`:
  - 3 변종: (a) playwright-stealth full, (b) 3 옵션 minimal, (c) options 없음 (control)
  - **첫 phase**: 각 변종 × 10 회 (총 30 호출) — 시간대 1개
  - **조기 중단 조건** (v2, codex MINOR 5):
    - phase 1 의 minimal vs full 차이 ≤5% + block 0 → phase 2 (전체 90) skip, "minimal 충분" 결론
    - block / 429 / CF challenge 연속 2회 또는 전체 3회 → 즉시 중단, "stealth 필수" 결론
  - **phase 2 (조건부)**: 각 변종 × 30 회, 시간대 3개 (0~6시 / 12~18시 / 18~24시)
  - **jitter**: 변종 순서 randomize + polite_sleep 에 2~5분 jitter 추가
- `results.csv` (변종, 시간대, status, latency, blocked_reason)
- README 결론 + commit 별도 (본 plan scope 외 = prod 단순화)

### Success criterion
- phase 1 = 30 호출 완료 + 조기 중단 결정
- (조건부) phase 2 = 90 호출 완료
- README 결론 3~5줄

### Rollback
- 실험만 — prod adapter 변경 X. 무비용.

### 미정
- robots/rate limit 회색지대 — polite_sleep + jitter + 조기 중단으로 최소화.

---

## 7. 종합 일정·체크리스트 (v2)

```
Phase A (직렬)
├─ Day 1 (0.5일)  Action #2  ArcaLive case .md
└─ Day 1.5~2.5    Action #3  vocab-ext 첫 호출 (response_branch_body, Reddit branch 만)
                   ├─ design (branch source kind + schema validate + prompt 추가)
                   ├─ smoke + 전체 config validate + handwritten 전체 회귀
                   └─ reviewer subagent PASS (rubric 9~12 출력 첨부 의무)

Phase B (병렬)
├─ Day 3~4        Action #1  Firecrawl /map (scripts/register.py post-probe)
├─ Day 3 (0.5일)  Action #4  llm-scraper generate() 비교 (recall + latency only)
└─ Day 3~7        Action #5  stealth 점검 (phase 1 → 조기 중단 → phase 2 조건부)
```

### 진행 전 사용자 확인 항목
1. Phase A 진행 OK? (vocab-ext SKILL 첫 dogfood — 실패 시 ADR 자체 재검토)
2. **Phase B 시작 전** (v2, codex NIT): Firecrawl API key 확보 (free tier 500 credit/월) — 없으면 #1 disabled
3. #5 phase 2 (90 호출) 시 robots 회색지대 — polite_sleep + jitter + 조기 중단 충분?

## 8. 본 plan 이 결론짓지 *않은* 것

- handwritten 4 어댑터 → config 전환 = #3 결과 가능해도 *전환 자체* 는 별 작업.
- 6번 (슬라이드) 범위 외.
- `dashboard /vocab-deferred` = 이미 commit `9d715f1`. 새 작업 X.
