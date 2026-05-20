# skill 실행 기록 DB 계획 — `case_runs` (rev 3 — 구현 완료)

> 작성 2026-05-16 / **rev 3 audit-2 후 β minimal 채택 + 구현 완료**. begin/end 패턴 폐기 (단일 commit 정책), 임시 파일 X. `bot/case_runs_meta.py` 가 schema/OUTCOMES 단일 진실원.
>
> 구현 자리: `scripts/case_log.py` (CLI log+query), `scripts/cases_index.py` (--backfill-db), `dashboard/cases_view.py` + 템플릿 셋, `.claude/skills/{hand-config,report-triage}/SKILL.md` 끝 단계 inject.
>
> 트리거: hand-config / report-triage skill 실행 흔적이 `docs/cases/*.md` 에만 남고, "개선이 일어나지 않았어도 시도 자체"는 기록 자리 X. 사용자가 *"대시보드에 triage·report 기록만 보여도 일단 만족"* 표현 — 1순위 deliverable = **dev 박스 dashboard 에 매 skill 실행 1줄씩 표시**. 2순위 = agent retrospect (deferred — 데이터 누적 후 가치 검증).
>
> grill-me (2026-05-16) + audit-1 결과 합의:
> - **DB row 매 실행 (코드 변경 없어도)** + **case .md 는 의미 있는 변경에만 (현 룰 유지)** + **DB 는 dev box only 별도 sqlite** + **enforce X (skill 명시만)**
> - **handcrafted outcome 신설** — 손-config / 손어댑터로 사이트만 작동시킨 케이스 분리 (코드 일반화 X). 13건 backfill 시 `🔧/🧩` 가 여기로.
> - **reviewer 는 query 하지 않음** — main thread 가 query 결과를 reviewer prompt 에 박는 기존 패턴 (자가개선 인프라 §1a step 7) 유지.
>
> 대조 검토: browser-use/browser-harness 의 `agent_helpers.py` + `domain-skills/<host>/*.md` 자가개선 모델 — 그쪽은 *절차적 엔진* 이라 site-specific playbook 가치 큼. 우리는 *선언적 엔진* (config = recipe) → 같은 자리 X. *runtime context 주입 X — 자가개선은 코드/prompt 변경 (fix_layer A~G) 으로 이미 커버*. 도입한 건 **agent retrospection 자리** + **사람 dashboard view** 만.

---

## 0. 배경

### 0a. 무엇이 부족한가

현재 skill 실행 후 흔적:
- `docs/cases/<slug>.md` — 코드 변경 발생한 케이스만, 사람이 narrative 작성. 13건 누적.
- `docs/cases/INDEX.md` — `cases_index.py` 가 frontmatter 표로 자동 생성.
- git log — commit 이 있을 때만, 메시지 자유.

부족:
1. **개선 안 일어난 실행 — 흔적 0** ("prompt 미세조정 시도, 효과 X, revert", "이미 손-config 있어서 selector 만 비교, 동일 출력" 등). skill 직접 실행 사례인데 안 보임.
2. **사람 dashboard 자리 X** — INDEX.md 표는 정적, 정렬·필터·case 본문 직접 jump 불가. dev 박스에서 "내가 어떤 사이트 시도했지" 빠른 회상 자리 X.
3. **agent retrospect 약함** — hand-config SKILL §6 step 2 가 `Grep '<failure_key>' docs/cases/` 권장하지만 fix_layer / files_changed / recency 조합 query 어려움. (낮은 우선순위 — 데이터 누적 후 가치 검증.)

### 0b. 무엇은 *추가 안* 하나

- **runtime context 주입 (Gemini 가 과거 case frontmatter 읽음)** — 폐기. frontmatter 는 *상태 라벨* 이지 *실행 가능 지식* X. 자가개선은 prompt rule 추가 (A) / 휴리스틱 추가 (C) / 인식기 확장 (F) 등 코드/prompt 변경으로 이미 됨.
- **per-host site-knowledge .md 신설** — 같은 이유. 정책 결정·last-verified 등은 기존 case .md frontmatter + `docs/크롤링 지침.md` + `configs/*.json` 로 충분.
- **DB row 강제 (pre-push hook 차단 등)** — 자가개선 인프라 audit-3 의 "markdown instruction ≠ infra" 교훈 적용 안 함. SKILL.md 명시만, 잊음 ~10% gap 수용.
- **case .md 항상 작성 강제** — no-change run 도 case .md 만들면 docs/cases noise. DB row 한 줄로 충분.

### 0c. 핵심 통찰

기록 두 종류 분리:

| 종류 | 형식 | 자리 | 빈도 |
|---|---|---|---|
| **실행 audit (uniform 1줄)** | DB row (`case_runs`) | dev box `output/cases.sqlite3` | 매 skill 실행 1회 |
| **narrative artifact** | `docs/cases/<slug>.md` markdown | git 추적 | 코드 변경 / 정책 결정 시만 |

DB row 는 *모든* 실행 균일. case .md 는 *의미 있는* 변경만 (현 SKILL §6 룰 유지). row 의 `case_md_slug` 컬럼이 두 자리 잇기.

### 0d. 사용자 우선순위

- **1순위 (즉시 가치)**: dev 박스 dashboard 에 매 skill 실행 row 표시 — "사용해봐야 알 수 있다" 단계, dashboard 자리만 만족 표현.
- **2순위 (deferred, 데이터 누적 후)**: agent retrospect (`§1.5` SKILL inject), pipeline-rot-review DB 활용, fix_layer 일관성 측정 등.

phase 분할 도 이 우선순위 따름 (§4).

---

## 1. 핵심 설계

### 1a. DB 파일

**`output/cases.sqlite3`** — dev box 전용 신규 sqlite. `bot.sqlite3` 와 분리 이유:
- bot.sqlite3 = N100 런타임 (subscriptions/reports/announcements 등 사용자 데이터).
- case_runs = dev 메타 (skill 실행 audit). N100 안 봄.
- 같은 파일 섞으면 ownership 혼란 + snapshot/scp 시 파일명 동일·내용 다른 사고 위험.

git 추적 X (`output/` 이미 ignore). 백업은 dev box 로컬 책임.

dashboard 에서 두 DB 동시 open: `dashboard/state.py` 에 `open_cases_conn()` 헬퍼 신규 추가 (기존 `open_conn()` 은 bot.sqlite3 그대로).

### 1b. 스키마

```sql
CREATE TABLE case_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,                  -- ISO8601 UTC, '2026-05-16T14:32:11Z'
    slug            TEXT NOT NULL,                  -- 시도한 사이트 slug
    url             TEXT,                           -- 원본 URL (auto-derive from FAILED.json/triage_queue)
    skill           TEXT NOT NULL,                  -- 'hand-config' | 'report-triage' | 'pipeline-rot-review' | ...
    outcome         TEXT NOT NULL,                  -- enum (CHECK 제약 X — backfill idempotent 위해)
    failure_keys    TEXT,                           -- JSON array, e.g. '["article_body_len"]'
    fix_layer       TEXT,                           -- 'C+D' / 'F' / NULL — 기존 A~G taxonomy 그대로
    files_changed   TEXT,                           -- JSON array of relative paths (auto-derive from git diff). 변경 X = '[]', 모름 = NULL.
    case_md_slug    TEXT,                           -- nullable, docs/cases/<slug>.md 링크
    reason          TEXT NOT NULL,                  -- 1-3줄 — 무엇 시도/왜 결과
    requested_by    TEXT,                           -- /preview 누른 디스코드 user (있으면)
    commit_sha      TEXT,                           -- skill 실행 마지막 commit (NULL=커밋 X)
    UNIQUE(slug, ts)
);
CREATE INDEX idx_case_runs_slug ON case_runs(slug);
CREATE INDEX idx_case_runs_ts ON case_runs(ts DESC);
CREATE INDEX idx_case_runs_layer ON case_runs(fix_layer);
CREATE INDEX idx_case_runs_user ON case_runs(requested_by);
```

`outcome` 6종 의미 (rev 2 — `handcrafted` 신설):

| outcome | 의미 | case .md? | 코드 변경? |
|---|---|---|---|
| `improved` | 추론 개선 — AUTO path 가 미지 사이트 더 잘 풂 (probe 휴리스틱 C / schema E / prompt 룰 A / retry D · 거부 필터 recognize_reject · register 거부 게이트) + 효과 검증. ADR 0005 | ✅ | ✅ |
| `handcrafted` | 수동 config — 자동이 못 푼 걸 직접 박은 패치(진보 X). 단일 config(configs/<slug>.json)·플랫폼 config(발급 recognizer)·손-adapter. fix_layer 무관(F 여도 handcrafted). ADR 0005 | ✅ | ✅ |
| `no_change` | 시도했지만 효과 X (revert 또는 동등 출력). 사이트 상태 변동 X | 보통 X | X |
| `rejected` | 정책상 거부 마커 (`.REJECTED.json` 또는 등록 거부) | ✅ | 가능 (preflight·휴리스틱 추가) |
| `rejected_with_policy` | no-change 인데 영구 기록 가치 정책 결정 ("이 SERP 류 휴리스틱 안 박기로 결정") | ✅ | X |
| `error` | skill 도중 미완 (Claude 죽음·사용자 abort·CLI 호출 자체 실패) | X | 변동 |

**중요 — outcome 은 mechanism 기준 (ADR 0005), fix_layer 와 1:1 X**:
- `improved` = 추론 개선 — 보통 fix_layer C/E/A/D + 거부 필터/게이트. 단 fix_layer F(엔진 코드)여도 발급 recognizer 면 `handcrafted`.
- `handcrafted` = 수동 config 패치 — fix_layer 키 X(단일 config) 이거나 F(플랫폼 config = 발급 recognizer)·adapter. fix_layer 무관.

13건 backfill 시 9건 (`🔧/🧩`) → `handcrafted`. 1건 (`🚫 + 후속 완료`, naver-cafe_31104609) → 손 분류 (`rejected_with_policy` + 별 row `improved`). 나머지 → 본문 본 후 분류 (§2).

`outcome` CHECK 제약 X 이유: backfill 시 unknown status 만나면 INSERT 실패 → idempotent 깨짐. 대신 CLI 가 enum 외 값 받으면 `error` 폴백 + warn print.

`files_changed` `'[]'` (빈 array) vs `NULL`: 명시 — *clean worktree 에서 log 호출* = `'[]'`. *log 호출이 git diff 못 derive* (git 명령 실패) = `NULL`. dashboard 표시: `'[]'` → "변경 없음", `NULL` → "(미상)".

`failure_keys` JSON array 인 이유 — `[FAIL]` 다중 동시 발생 가능. LIKE 매칭으로 단일 key 검색 (`failure_keys LIKE '%article_body_len%'`).

### 1c. CLI — `scripts/case_log.py`

세 subcommand:

**`begin`** — skill 시작 시 begin/end 패턴의 시작:
```bash
python scripts/case_log.py begin --slug <slug> --skill hand-config
```
효과: `output/.case_run.<slug>.json` 신규 작성, `{start_sha: <git rev-parse HEAD>, started_at: <ISO8601>}` 박음. 같은 slug 의 이전 begin 파일 있으면 overwrite + warn (이전 실행 로깅 미완 가능성).

**`log`** — skill 끝 마지막 단계. 매 실행 1회 (코드 변경 X 도):
```bash
python scripts/case_log.py log \
  --slug <slug> --skill hand-config \
  --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \
  --reason "<1-3줄>" \
  [--fix-layer <C+D>] [--failure-keys <key1,key2>] [--case-md-slug <slug>]
```

required: `--slug`, `--skill`, `--outcome`, `--reason`. 나머지 optional.

자동 derive (CLI 안):
- `ts` = `datetime.utcnow().isoformat() + 'Z'`
- `commit_sha` = `git rev-parse HEAD` (현재 HEAD).
- `files_changed`:
  1. `output/.case_run.<slug>.json` 의 `start_sha` lookup → `git diff --name-only <start_sha>..HEAD`.
  2. begin 파일 없으면 → `git diff --name-only HEAD~1..HEAD` 폴백.
  3. git 명령 실패 → `NULL`.
  4. clean worktree (변경 없음) → `'[]'`.
- `url`, `requested_by` = `output/poll_state/<slug>.FAILED.json` + `output/triage_queue.jsonl` slug 매칭. 없으면 NULL.

`log` 성공 후 `output/.case_run.<slug>.json` 삭제 (begin/end 닫음).

**`query`** — agent retrospect (P4 phase 에서 SKILL inject):
```bash
python scripts/case_log.py query [--slug X] [--host H] [--failure-key K] \
                                 [--file-touched PREFIX] [--layer L] \
                                 [--requested-by USER] [--recent N] \
                                 [--limit 20] [--format table|json]
```

조건 AND 조합. default `--limit 20 --format table`. table 컬럼: `slug | ts | outcome | layer | failure_keys | reason(50c) | case_md_slug`.

DB 부재 (fresh clone, N100) → "DB 없음, grep fallback 권장" 안내 + exit 0.

**parse_case 공유** — `cases_index.py` 의 `parse_case(path)` 함수를 그대로 import 사용 (frontmatter parse 두 자리 만들지 X). 필요 시 `scripts/_caselib.py` 같은 공통 모듈로 옮김.

### 1d. write path — Claude 가 명시 호출, 강제 X

`hand-config/SKILL.md` §1 진입 직후 (begin) + §5 끝 (log) 두 자리 inject:

```markdown
## §0.5. case_runs begin (필수, 진단 시작 직전)

\`\`\`bash
python scripts/case_log.py begin --slug <slug> --skill hand-config
\`\`\`

`output/.case_run.<slug>.json` 에 시작 sha 캡쳐 — 다중 commit 케이스에서 files_changed 정확히 derive 위해.
```

```markdown
## §5.10. case_runs log (필수, skill 마지막 단계 — N100 deploy 이후)

skill 실행 *항상* 끝에 한 번 — 코드 변경 있든 없든:

\`\`\`bash
python scripts/case_log.py log \
  --slug <slug> --skill hand-config \
  --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \
  --reason "<1-3줄 — 무엇 시도, 왜 그 결과>" \
  [--fix-layer <C+D>] [--failure-keys <key>] [--case-md-slug <slug>]
\`\`\`

outcome 분류:
- `improved` — fix_layer A/B/C/D/F/G 코드 일반화 + 효과 검증
- `handcrafted` — 손-config / 신규 손어댑터로 그 사이트만 작동 (fix_layer 키 X)
- `no_change` — 시도했으나 효과 X
- `rejected` — 정책 거부 마커
- `rejected_with_policy` — no-change 인데 영구 기록 가치 정책 결정
- `error` — skill 도중 미완 (이 row 는 사람이 사후 박기 — 정상 흐름 안에서 outcome=error 박지 X)

**강제 안 함**. 잊어도 push 차단 X — 대신 mitigation 셋:
1. 이 단계가 SKILL §5 마지막 — commit·deploy 후 reflex
2. reviewer prompt 에 main thread 가 query 결과 박음 (§7) — soft check
3. `pipeline-rot-review` SKILL 분기 점검 항목 추가 (§5)
```

`hand-config-reviewer` 호출 시 (현 SKILL §7) main thread 가 query 결과를 prompt 에 박음:

```python
# main thread 측 (Claude Code) — reviewer 호출 *전*:
import subprocess, json
qresult = subprocess.run(
    ["python", "scripts/case_log.py", "query", "--slug", slug, "--recent", "1", "--format", "json"],
    capture_output=True, text=True
).stdout
# qresult = '[]' 또는 '[{"slug":"...","ts":"...","outcome":"improved",...}]'

Agent(subagent_type='hand-config-reviewer', model='sonnet', prompt=f'''
  ## 변경 diff
  {diff}
  
  ## case .md frontmatter
  {case_md_text}
  
  ## probe_smoke 결과
  {smoke_result}
  
  ## case_runs row (이번 실행, recent 1day)
  {qresult}
  
  검증:
  - case_runs row 가 비었으면 → main thread 가 log 호출 잊음. PASS 가능 but warn.
  - row 의 fix_layer / files_changed / failure_keys 가 case .md frontmatter 와 일치하나? 모순 = FAIL.
  - row 의 outcome 이 case .md status 와 일치하나? (🔧 → handcrafted, ✅ → improved 등)
''')
```

reviewer 는 prompt JSON 만 보고 판단. Bash X, sqlite query X. 자가개선 인프라 §1a step 7 패턴 그대로.

### 1e. read path — agent retrospect (P4 — deferred)

`hand-config/SKILL.md` 새 §1.5 (P4 phase 에서 inject, 지금 X):

```markdown
## §1.5. 과거 사례 retrospect (진단 직전, 권장)

\`\`\`bash
python scripts/case_log.py query --slug <slug>             # 이 slug 재시도?
python scripts/case_log.py query --host <host>             # 같은 host 다른 slug 처리 이력
python scripts/case_log.py query --failure-key <FAIL key>  # 같은 [FAIL] 패턴 처리
\`\`\`

각 0건 → 새 패턴 자유 진단. 1건+ → 그 케이스 fix_layer 와 *일관 유지*. 다른 layer 박을 거면 case .md 본문에 이유 명시.

기존 SKILL.md §6 step 2 의 grep 권장은 이 §1.5 가 대체 — 줄 갱신.
```

P4 inject 시점: row 30+ 누적 후 (한 달~) — 데이터 적을 때 query 대부분 0건 → SKILL noise.

### 1f. dashboard view (P3 — 1순위 deliverable)

`dashboard/` 에 새 라우트 `/cases` + nav 탭 "Cases":

**페이지 구성**:
- 좌측 필터 사이드바 (skill multi-select / outcome multi-select / fix_layer text contains / failure_key text contains / requested_by text / 기간 last 7|30|90|all)
- 중앙 표 — `ts | slug | skill | outcome | fix_layer | failure_keys | reason(80c) | files | case`
  - `files` = files_changed 카운트 (호버 = 풀 list)
  - `case` = case_md_slug 있으면 markdown render 링크 (별 라우트 `/cases/<slug>/md` 가 docs/cases/<slug>.md render)
  - 정렬 = ts DESC default
- 상단 미니 stats (50+ row 후 의미) — outcome 분포 / fix_layer top 5 / files_changed prefix top 5. 50 미만이면 stats 숨김.
- row 클릭 → 우측 패널: full reason + commit_sha → GitHub URL build 링크 + case .md render (있으면)

기존 dashboard 의 nav 구조 따름 (`dashboard/templates/` 의 base 템플릿 reuse).

`open_cases_conn()` 헬퍼 신규 — `dashboard/state.py` 추가.

상세 와이어 (column 폭, 색상 등) 별도 phase 또는 사용 후 조정.

---

## 2. 마이그레이션 — 기존 13 case backfill

`scripts/cases_index.py` 가 이미 frontmatter 파싱. 확장:

```bash
python scripts/cases_index.py --backfill-db output/cases.sqlite3
```

frontmatter → DB row 매핑:
- `slug, url, date` 직접
- `ts` = `date + 'T00:00:00Z'` (정확 시각 X, 일자만)
- `failure_keys`, `fix_layer` 직접
- `outcome` = status 이모지 + 본문 word 매칭으로 추론:

| status pattern | outcome |
|---|---|
| `✅ 자동` (recognizer/probe 자동) | `improved` |
| `✅ 손작성 config` (손-config 인데 자동 분류) | `handcrafted` |
| `🔧 손 config` / `🔧 손작성 config` | `handcrafted` |
| `🧩 손어댑터` | `handcrafted` |
| `🚫 거부` (단일) | `rejected` |
| `🚫 + 후속 완료` (복합) | `rejected_with_policy` + 별 row `improved` 두 row 박음 |
| `❌ FAILED` | `error` (드물 — 미해결만) |
| 기타 | `error` 폴백 + warn print (사람 사후 분류) |

- `skill` = 모두 `'hand-config'` (당시 skill X, 추정)
- `reason` = case .md 본문 첫 단락 truncate 200c
- `case_md_slug` = `slug` 자기 자신
- `files_changed` = frontmatter `engine_files_touched` + `adapters_changed` 합집합 (있으면) → JSON array. 둘 다 없으면 `NULL` (handcrafted 면 `configs/<slug>.json` 1건 라도 박을 수 있지만 정확도 낮음 → NULL).
- `commit_sha` = `git log --grep=<slug> --pretty=%H -1` heuristic. slug 가 commit msg 에 안 박힌 경우 다수 → NULL 비율 높음, 그게 정직.
- `requested_by` = frontmatter `requested_by` (있으면), 없으면 NULL

idempotent — `(slug, ts)` UNIQUE 충돌 시 skip.

backfill 후 검증 (사람 손):
```bash
python scripts/case_log.py query --recent 365 --format table
# 13~14 row 출력 (🚫+후속 한 건이 두 row 가 됨)
```

각 row 의 outcome / files_changed 가 직관과 맞는지 사람이 한 번 훑음. 틀리면 SQL 직접 UPDATE (또는 frontmatter 갱신 후 재 backfill).

---

## 3. `cases_index.py` / INDEX.md 운명

INDEX.md 유지 가치:
- grep 가능 단일 markdown — terminal 작업 빠름
- git diff 에 등록 추이 시각화 (PR review 시 사람 본다)

DB 도입 후 INDEX.md 가 *없어도 되는가?* — 기능 면 DB superset. 단 git-trackable markdown 의 보조 가치 (PR diff·grep) 는 별. 둘 다 유지.

`cases_index.py` 변경:
- 기존 동작 유지 (INDEX.md 생성)
- `--backfill-db <path>` 플래그 추가 (위 §2)
- `parse_case` 함수 export — `case_log.py` import (frontmatter parse 한 자리)

INDEX.md 가 200줄 넘으면 (~50 case 후) cap 도입 검토 — last 30일만 표로, 그 이상 "older cases: see dashboard". 지금 13건이라 cap 불필요.

---

## 4. phase 분할 (사용자 우선순위 따름)

| phase | 산출 | 검증 | 차단? |
|---|---|---|---|
| **P1 schema + write CLI + SKILL inject (write only)** | `output/cases.sqlite3` 신규, `case_log.py {begin,log}`, hand-config + report-triage SKILL §0.5 / §5.10 추가 | `case_log.py log` smoke + sqlite3 CLI 직접 query 1건 박힘 확인 | none |
| **P2 backfill** | `cases_index.py --backfill-db`, 13건 → 14 row 확인 | row count 14, sample row 사람 검증 (outcome 매핑) | P1 |
| **P3 dashboard view** | `dashboard/cases` 라우트 + nav 탭 + 필터 + 표 + row 클릭 | localhost:8765/cases 접속, 표·필터·case .md jump 동작 | P2 (1순위 deliverable) |
| **P4 read CLI inject (deferred)** | hand-config SKILL §1.5 추가, reviewer prompt 에 query 결과 inject (main thread 책임) | 다음 hand-config 실행 시 reviewer 가 row 검증 | P1 + 30+ row 누적 |
| **P5 advanced stats / pipeline-rot-review DB integration (deferred)** | dashboard stats 패널, `pipeline-rot-review` SKILL 의 DB 활용 항목 | row 50+ 후 가치 평가 | P3 + 50+ row |

P1~P3 = 1순위 (사용자 즉시 만족). P4·P5 = 데이터 누적 후 가치 검증 — 한 달 후 ROI 평가 (§5b).

각 phase 끝 사용자 확인 — 다음 phase 진행 전.

---

## 5. 안전·회귀·평가

### 5a. 안전

**절대 금지**:
- `output/cases.sqlite3` git commit (실수 add)
- N100 으로 cases.sqlite3 sync (dev only)
- `output/.case_run.<slug>.json` 수동 편집 (CLI 가 관리)

**확인 후 진행**:
- schema 변경 (컬럼 추가) — 마이그 SQL 별 phase, backfill 재돌림. CHECK 제약 X 정책 유지.

**자율 허용**:
- `case_log.py {begin,log,query}` 호출
- `cases_index.py --backfill-db` 재실행 (idempotent)

### 5b. 한 달 후 평가 (P4 가기 전 자리)

사용자 명시: "지금도 skill 의도대로 동작 안 하고 개선하고 있는 단계라 별 효과 없을 것 같다 — 사용해봐야 알 수 있다". 1순위 만족 (dashboard) 외 효과는 1개월 후 측정:

- DB row 누적 N — 30+ 면 P4 (read CLI inject) 가치 보임
- dashboard /cases 페이지 사람 접속 횟수 — 0 이면 1순위 가치 자체가 환상
- gap 율 — `git log` 와 row count 비교, 30% 넘으면 mitigation 강화 (예: pre-push hook 의 warn 추가)
- `outcome` 분포 — `handcrafted` vs `improved` 비율 — 자가개선 인프라 §0c KPI baseline

세 지표 다 0 또는 ROI 약하면 → P4·P5 영구 deferred, P1~P3 만 유지 (deletion 비용 없음, dev only).

### 5c. 알려진 한계 (정직)

- **gap ~10%** — Claude 잊음 + error path. *통계 정확도 ~90%*. 결정 영향: rot-review 등 SKILL 이 절대값 신뢰 X (추세만).
- **기존 13 case 의미 라벨 변경** — 🔧/🧩 → `handcrafted` (이전엔 fix_layer-N/A). 자가개선 인프라 §0c 의 *손-config = fix_layer 키 X* 표현 그대로 — outcome 분리만 추가. 자가개선 인프라 문서 별 갱신 필요 (이 plan 와 함께 동시 수정 권장).
- **runtime 자동 등록 성공률 무변동** — Gemini 가 DB 안 봄. 자동 성공률은 fix_layer A~G 변경에 의존, 이 plan 은 *측정 자리 제공* 만.
- **N100 사용자 영향 0** — dev box only.

---

## 6. 관련 문서

- `CLAUDE.md` — dev box / N100 분리, 안전 동작
- `docs/자가개선 인프라 계획.md` — hand-config 자가개선 v3 (이 계획의 상위 — `handcrafted` outcome 신설로 §0c "손-config = fix_layer 키 X" 표현 갱신 필요)
- `.claude/skills/hand-config/SKILL.md` — 손-config 워크플로우 (§0.5 + §5.10 신설, P4 시 §1.5 추가)
- `.claude/skills/report-triage/SKILL.md` — 신고 처리 (§0.5 + §끝 신설)
- `.claude/agents/hand-config-reviewer.md` — reviewer subagent (변경 X — main thread 가 query 결과 prompt 에 박는 패턴 그대로)
- `.claude/skills/pipeline-rot-review/SKILL.md` — 누적 분석 (P5 시 DB query 활용 자리)
- `docs/cases/INDEX.md` — frontmatter 자동 표 (병행 유지)
- 참고 (도입 안 함): browser-use/browser-harness — agent_helpers.py + domain-skills/ 자가개선 모델 (절차적 엔진용 — 우리 선언적 엔진엔 부적합)
