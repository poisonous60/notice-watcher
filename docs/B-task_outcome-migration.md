# B-task: outcome 분류 mechanism 마이그레이션 (다음 세션 바로 실행)

ADR 0005 결정의 실행 단계. **A(어휘+ADR)는 2026-05-20 완료**. 이 문서 = 남은 코드/데이터 마이그.

배경 한 줄: `outcome` 의미를 scope→mechanism 으로 re-cut. config 발급 recognizer(=플랫폼 config = 자동이 못 푼 걸 박은 수동 config 패치)는 `improved` 아니라 `handcrafted`. 상세 = `docs/adr/0005-outcome-mechanism-not-scope.md`, 어휘 = `CONTEXT.md` (등록 실패 / 추론 개선 / 수동 config / 단일 config / 플랫폼 config / recognizer 2종).

## 핵심 룰 (마이그 판정 기준)

case 의 **주된 산출** 이:
- 아는 것에 답 박음 (단일 config / 플랫폼 config / 손-adapter) → `handcrafted`
- AUTO path 가 *미지* 사이트 더 잘 풀게 함 (probe 휴리스틱 C / schema E / prompt A / retry D / reject-gate recognizer / register 플로우 / blacklist 학습) → `improved`
- mixed 면 **dominant** 로. (예: google-news = recognizer+adapter(수동 config) + `_STABLE_ID_RE` cap fix(약한 추론개선) → main 은 플랫폼 config → `handcrafted`)

## Step 1 — enum 정의 갱신 (단일 진실원)

`bot/case_runs_meta.py` line 12-13 주석 재작성:
```python
"improved",     # 추론 개선 — AUTO path 가 미지 사이트 더 잘 풂 (probe휴리스틱/schema/prompt/retry/reject-gate/register플로우). ADR 0005
"handcrafted",  # 수동 config — 자동이 못 푼 걸 직접 박은 패치, 진보 X (단일 config / 플랫폼 config = 발급 recognizer / 손-adapter). ADR 0005
```
(`OUTCOME_LABELS` 값 `✨ improved`/`🔧 handcrafted` 그대로 OK — 키 안 바뀜, drift assert 통과.)

## Step 2 — SKILL §6.5 outcome 표 재정의

`.claude/skills/hand-config/SKILL.md` (+ `.agents/skills/hand-config/SKILL.md` 동일본 — **둘 다**) 의 outcome enum 표:
```
| improved | 추론 개선 — AUTO path 가 미지 사이트 더 잘 풂 (fix_layer C/E/A/D·reject-gate·register플로우) |
| handcrafted | 수동 config — 자동이 못 푼 패치(진보 X). 단일 config·플랫폼 config(발급 recognizer)·손-adapter. fix_layer 무관(F 여도 handcrafted) |
```
"handcrafted = fix_layer X" 문구 폐기 — 플랫폼 config 는 handcrafted + fix_layer F.
§2e·§3 step 8·트랙B 서술 중 "recognizer = 일반화/개선" 뉘앙스도 "플랫폼 config = 수동 config 패치" 로 손볼 것 (grep `일반화` in SKILL).

## Step 3 — 6 case frontmatter flip (improved → handcrafted)

config 발급 recognizer case 6개 — 각각 dominant=수동 config 재확인 후 `outcome: improved` → `outcome: handcrafted`:

- `docs/cases/google-news_gnews_gemini_3.5_flash_270bb44a.md` — **추가**: status 의 "✅ 일반화 완료" → "✅ 플랫폼 config 등록"; 본문 제목 "F-recognizer 일반화" → "플랫폼 config"; 어휘 박스 갱신 (A 세션에서 "일반화" 로 박아둔 것 정정)
- `docs/cases/cafe.naver.com_home.md`
- `docs/cases/discourse_discuss.python.org_16ebc619.md`
- `docs/cases/naver-blog_dhyana69_85ae2dd0.md`
- `docs/cases/naver-blog_ghangth_5a895e5f.md`
- `docs/cases/tistory_leedakyeong_e0e58b0f.md`

**flip 안 함 (improved 유지)** — reject-gate/blacklist/infra recognizer 는 추론개선:
`infra_article_page_reject_*`, `infra_*_learned_blacklist_skip_*`, `infra_single_article_gate_*`, `infra_gate_false_positive_fixes_*` 등. (recognizer=Y 여도 *거부 게이트* 라 improved 맞음.)

확인 명령: `for f in <6개>; do grep -H "^outcome:" $f; done` 로 현재값 보고, flip 후 재확인.

## Step 4 — DB re-sync

```
python scripts/cases_index.py --backfill-db output/cases.sqlite3
```
주의: `case_runs` 는 `UNIQUE(slug, ts)`. backfill row 와 `case_log.py log` row 가 같은 slug 에 둘 있을 수 있음 — 6 case 의 기존 logged row(outcome=improved)가 남아있으면 dashboard 에 옛값 보임. backfill 이 덮는지 append 인지 `cases_index.py` 동작 확인 후, 필요 시 해당 row 수동 UPDATE:
```sql
UPDATE case_runs SET outcome='handcrafted' WHERE slug IN (<6 slug>) AND outcome='improved';
```

## Step 5 — dashboard 확인

`dashboard/cases_view.py` 는 `OUTCOME_LABELS` import — 코드 변경 X. `/cases` 탭에서 6 case 가 `🔧 handcrafted` 로 보이는지 + improved 카운트가 줄었는지 눈으로 확인 (dev 박스 `python scripts/dashboard.py`).

## Step 6 — 검증 + commit + 배포

- `python scripts/probe_smoke.py` 그린 (case_runs_meta drift assert 포함).
- commit: `[fix-layer: none] outcome 분류 mechanism 마이그 (ADR 0005)` — 단일 commit (meta + SKILL ×2 + 6 case + DB backfill 산출).
- push → N100 pull. **bot/case_runs_meta.py 변경** → `systemctl --user restart notice-bot.service` (bot import). dashboard 는 dev-only.
- 완료 후 ADR 0005 Status "마이그 미실행" → "마이그 완료 <날짜>" 갱신. 이 문서(`B-task_outcome-migration.md`) 삭제.

## 주의

- 6 case flip 전 **각각 case 본문 읽고 dominant mechanism 재판정**. 6개 다 config 발급이 main 으로 보이지만 (예: discourse 가 recognizer 외에 schema 개선도 했으면 dominant 재고). 기계적 flip 금지.
- `arca-live_trickcal_6703bf64.md` 는 *이미* handcrafted (fix_layer=-) — 손 안 댐. 단 정합성상 fix_layer 에 F(arca_live.py recognizer) 박을지는 선택 (지금 비대칭이지만 outcome 은 맞음).
