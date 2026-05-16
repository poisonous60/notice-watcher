# cases 저장 방법 (recipe)

> 작성 2026-05-16. case 한 건 = `docs/cases/<slug>.md` 한 파일 + (자동) `output/cases.sqlite3` 의 `case_runs` row 1+개. 대시보드 `/cases` 가 row 표시, INDEX.md 가 frontmatter 표.
>
> 설계 배경: `docs/case_runs DB 계획.md` (rev 3). 본 문서는 **실행 recipe**.

---

## 1. 언제 case 한 건 만드나

| 조건 | 만든다 |
|---|---|
| 코드/prompt/heuristic 변경 일어났음 (fix_layer A~G 중 하나) | ✅ |
| 손-config / 손어댑터 작성 — 그 사이트만 작동시킴 | ✅ |
| 정책 결정 (rejected/rejected_with_policy 영구 기록 가치) | ✅ |
| 시도했지만 no_change — 다음 사람이 알아야 할 진단 결과 | ✅ (얕게) |
| 자동 등록 그냥 성공, 운영 노트 X | ❌ |

판정 흐름: *코드/config/정책에 영향이 남는가?* yes → case 만들어. no → git log 만으로 충분.

---

## 2. 두 가지 경로

### 2a. hand-config 스킬 자동
사용자가 `/triage` 또는 "FAILED 큐 처리" 의도로 skill 호출 시 `.claude/skills/hand-config/SKILL.md` 가 모드 B 단계 따름. 절차 (요약):

1. 진단 (FAILED.json + probe artifact 읽기)
2. fix (track A: 손-config / track B: 시스템 자가개선 = recognizer/probe/prompt 손질)
3. probe_smoke 회귀 검증
4. **commit + push** (단일 commit 정책)
5. `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py --backfill-db output/cases.sqlite3`
6. `python scripts/case_log.py log --slug … --skill hand-config --outcome … --reason …` (audit row 추가)
7. 사용자 신고면 봇 `/resolved <report_id>` 응답
8. N100 단일 SSH (pull + register if needed + bot restart)

이게 *standard* 경로. 본 문서의 나머지는 *예외* (스킬 밖) 경로.

### 2b. 스킬 밖 — 엔진 픽스 / 즉석 case (이 케이스)
사용자가 직접 "이 hang 잡아라" 같이 요청 → 코드 fix 하고 끝나는 흐름. 스킬이 자동으로 case 안 만들어줌 → **사람이 손으로 case .md 작성 + cases_index 호출** 필요.

순서:

1. 코드/probe/prompt fix → audit (`code-audit-reviewer` agent 호출) → 회귀 검증 (probe_smoke, dev box 단독 reproduce)
2. **commit + push** (pre-push hook 이 probe_smoke 자동 — fail 이면 차단)
3. `docs/cases/<slug>.md` 작성 (§3 의 frontmatter + body 양식)
4. `python scripts/cases_index.py --backfill-db output/cases.sqlite3`
5. case .md + INDEX.md 별도 commit + push (단일 commit 묶음에 못 넣은 케이스 — fix commit 이미 push 끝났으면 docs 만 별 commit OK)
6. N100 `git pull --ff-only` (코드 변경 있었으면 `systemctl --user restart notice-bot.service` 까지)

case_log.py 의 `--skill bug-fix` 같은 audit row 는 *선택* — skill 호출 아닌 즉석 작업이라 audit 가치 낮음. 생략 OK.

---

## 3. frontmatter 양식 — 표준 키

```yaml
---
slug: <필수 — 사이트 slug 또는 사건 식별자>
url: <필수 — 원본 URL 또는 N/A>
status: <필수 — 이모지 + 1줄 한국어. dashboard INDEX 에 그대로 노출>
outcome: <필수 — 아래 표준 값 6개 중 하나>
date: <필수 — YYYY-MM-DD. ts 폴백용>
fix_layer: <선택 — A/B/C/D/F/G 또는 결합 (C+D). 없으면 비워둠>
failure_keys: <선택 — [array]. 진단에서 발견한 실패 키>
config_strategy: <선택 — httpx_html / httpx_json / handwritten 등>
adapters_changed: <선택 — [array]. 손어댑터 변경 시>
engine_files_touched: <선택 — [array]. engine/probe/bot/scripts 등>
tags: <선택 — [array]. 자유 라벨 (silent-death, anti-bot 등)>
requested_by: <선택 — Discord 사용자 또는 N/A>
---
```

### outcome 표준값 6개 (`bot/case_runs_meta.py:OUTCOMES`)

| 값 | 의미 |
|---|---|
| `improved` | fix_layer 기반 코드 일반화 + 효과 (이 사이트만 X, 다른 사이트도 같은 룰 혜택) |
| `handcrafted` | 손-config / 손어댑터 — 그 사이트만 작동 (룰 일반화 X) |
| `no_change` | 시도했지만 효과 X (실패 분석만 남김) |
| `rejected` | 정책 거부 (게시판 아님, robots 차단 등) |
| `rejected_with_policy` | no-change + 영구 정책 결정 (예: cafe.naver.com 의 본문 추출 차단) |
| `error` | skill 도중 미완 — 정상 흐름엔 X |

비표준 outcome (예: `engine-fix`) 도 DB row 자체엔 박히지만 dashboard 필터 dropdown 에 안 뜨고 통계도 빠짐. 가능하면 6개 중 하나로 매핑 (엔진 픽스 → `improved` 권장).

---

## 4. body 양식

본문은 narrative — 6 섹션 권장:

```markdown
## 무엇이 일어났나
사용자 시점 증상 + 진단 흔적 (jobs row, ps tree, /proc/wchan, instrumentation trace 등).

## 왜 문제인가
1. 직접 원인 (코드/룰 측면)
2. 사용자 영향 (silent 죽음, triage 오염 등)
3. 운영자 영향 (재발 패턴, 진단 어려움)

## 픽스 (fix_layer: …)
정확히 어느 파일 어느 함수 어떻게 바꿨는지. diff 형태 권장.

## 영향
- 회귀 risk
- false positive 가능성
- 다른 사이트들 받는 혜택

## 회귀 검증
- probe_smoke 결과
- dev box reproduce
- audit subagent 결과

## 남은 정리
- 후속 작업 (별 commit)
- N100 잔여 state 청소
```

§5 `cases_index.py` 의 `_extract_first_paragraph` 가 첫 `##` 섹션 본문을 reason 필드로 캡쳐 — **"무엇이 일어났나" 의 첫 단락을 200자 이내로 의미있게**.

---

## 5. ts 가 어떻게 박히나

`scripts/cases_index.py:backfill_db` 가 `case_runs.ts` 컬럼 채울 때 우선순위:

1. **commit 시각 (1순위)** — `git log -1 --pretty=%cI --grep <slug>` 가 찾은 commit 의 committer 시각, UTC `YYYY-MM-DDTHH:MM:SSZ` 형식. case .md 의 fix 가 박힌 *그 commit* 의 시각.
2. **frontmatter `date` 의 UTC 자정 (폴백)** — `date: 2026-05-16` → `2026-05-16T00:00:00Z`. commit 메시지에 slug 안 박힌 옛 case 만 해당.

같은 slug 가 outcome 여러 개 (e.g. `rejected_with_policy` + `improved` split) 면 outcome[i>0] 은 base ts + i 초.

**dashboard `/cases` 정렬 = ts DESC** → 최근 commit 한 case 가 위. 그래서 commit 메시지에 slug 박는 게 중요 (체크리스트 §6).

---

## 6. commit 체크리스트 (case + fix 묶을 때)

단일 commit 정책 (hand-config SKILL.md §5 step 6):

- [ ] commit 메시지 *제목* 또는 *body* 에 case slug 박힘 (cases_index 의 git grep 대상). 예: `host_ncs-go-kr_blind_ddd2b021 — probe 룰 정정`
- [ ] 한 commit 안에: 코드 fix + case .md + INDEX.md 업데이트 + (있으면) hand-config 손-config 묶음. 다중 commit 시 `case_log` 의 `files_changed` derive 가 첫 commit 만 캡쳐 → 손실.
- [ ] pre-push hook 이 probe_smoke 자동 — fail 이면 차단. `--no-verify` **금지**.
- [ ] push 후 case_log.py log 호출 (hand-config 스킬일 때만 — audit row).

스킬 밖 즉석 case (§2b) 는 단일 commit 정책 면제 — fix commit 따로, docs commit 따로 OK.

---

## 7. DB 운영

### 7a. 평소 backfill
case .md 추가/수정 후:
```
python scripts/cases_index.py --backfill-db output/cases.sqlite3
```
이게 INDEX.md 갱신 + DB INSERT (UNIQUE 충돌 시 skip). 멱등.

### 7b. 자정 ts 정리 (한 번)
2026-05-16 이전 backfill 한 row 들은 ts 가 `T00:00:00Z` 자정으로 박혀 정렬 불안정. commit 시각으로 통일하려면:
```
python scripts/cases_index.py --backfill-db output/cases.sqlite3 --rebuild
```
`case_runs` 전체 DELETE 후 재삽입. **단 case_log 가 박은 audit row (frontmatter 없는 row) 도 같이 사라짐**. 보존하려면 사전에 `sqlite3 output/cases.sqlite3 .dump > backup.sql` 백업.

### 7c. case_log audit (선택)
스킬이 끝날 때 audit row 한 줄 박는 자리:
```
python scripts/case_log.py log \
  --slug <slug> --skill <hand-config|report-triage> \
  --outcome <표준값 6 중 1> \
  --reason "<한국어 1줄 — 무엇을 했고 왜>" \
  [--fix-layer A] [--failure-keys k1,k2]
```
commit 직후 호출 (commit_sha 자동 캡쳐). 스킬 밖 즉석 case 는 생략 OK.

---

## 8. dev box only — N100 안 가져감

`output/cases.sqlite3` 는 gitignore 안 (`output/` 통째). N100 에 안 push, dev box 만 봄. `docs/cases/*.md` + INDEX.md 는 git 추적이라 양쪽 동기.

이유: dashboard `/cases` 도 dev box only — N100 대시보드 안 돔. case_log + cases_index 가 박는 row 들은 *dev 박스 작업 audit* 라서 N100 으로 갈 의미 X.

---

## 9. 관련 파일

| 자리 | 역할 |
|---|---|
| `docs/cases/<slug>.md` | narrative artifact, git 추적, dashboard `/cases/<slug>/md` 가 렌더 |
| `docs/cases/INDEX.md` | frontmatter 자동 표 (`cases_index.py`) |
| `output/cases.sqlite3` | dev box only DB — dashboard `/cases` 표 source |
| `bot/case_runs_meta.py` | schema + OUTCOMES 단일 진실원 |
| `scripts/cases_index.py` | INDEX 생성 + DB backfill (`--rebuild` 지원) |
| `scripts/case_log.py` | 매 skill 실행 audit row CLI |
| `dashboard/cases_view.py` | `/cases` + `/cases/<slug>/md` 라우트 |
| `.claude/skills/hand-config/SKILL.md` | hand-config 흐름 — case 자동 생성 자리 |
| `docs/case_runs DB 계획.md` | rev 3 설계 — 본 recipe 의 배경 |
