---
name: report-triage
description: >-
  사용자가 봇에서 `/report` 한 구독 문제를 dev박스에서 자동으로 진단·수정·배포·해결 처리하는 워크플로우.
  "report 들어온 거 처리", "신고 triage", "사용자 신고 고쳐줘", "report-triage" 라고 할 때 사용.
  이 프로젝트 (`poisonous60/notice-watcher` 의 dev박스 clone) 전용. hand-config 와 평행 — 그 쪽은
  자동 등록 실패(FAILED.json) 처리, 이 쪽은 *등록은 됐지만 결과가 잘못된* 사용자 신고 처리.
---

봇 사용자가 `/report <slug> <issue>` 로 본인 구독 결과가 이상하다고 신고하면 N100 의 `bot.sqlite3:reports`
테이블에 `open` 상태로 쌓인다. 이 스킬은 그것을 dev박스에서 한 번에 끝까지 처리하는 절차다.
**추측하지 말고 아래 순서대로 — 각 단계 실제 산출물을 확인하며 진행.**

## 먼저 펼쳐 볼 것 (필요한 만큼만)
- `bot/inspector.py` — 진단 라이브러리. 어떤 휴리스틱 태그가 무슨 의미인지 docstring + `diagnose()`. 새 진단 룰은 여기 추가.
- `scripts/inspect_subs.py` — dev박스 CLI. 모든 단계가 이걸로.
- `bot/admin.py` — 봇 안에서 같은 데이터를 보는 명령(`/admin recent|reports|inspect|fetch|resolve`). owner 가 Discord 에서 빠르게 확인할 때 쓰는 경로.
- `engine/recognizers/<plat>.py` — 알려진 플랫폼 인식기. *recognizer 가 query 를 통째로 무시*하던 류의 버그(예: arca-tab `?category=` 무시)가 신고의 대표 원인. 새 인식기 룰 추가 시 같이 [`engine/recognizers/__init__.py`](../../engine/recognizers/__init__.py) 의 자동 발견 동작 활용.
- `docs/운영 메모.md` §4(슬래시 명령) · §6(state 파일) · §7(강제 재등록) · §8(dev → N100 배포) — 데이터 위치와 배포 절차의 진실의 원천.
- `docs/사이트별 등록 시도 기록.md` — 사이트별 시도/해결 로그. **끝나면 항목 추가/갱신**(이 신고로 어떤 사이트의 어떤 버그를 어떻게 고쳤는지).
- 기존 패턴 참고: `hand-config` 스킬 모드 B 가 같은 dev→N100 흐름이지만 *FAILED 자동등록* 대상. 이 스킬은 *등록 후 결과 깨짐* 대상.

---

## 워크플로

### 1. snapshot pull (라이브 데이터를 dev박스로)
```
python scripts/inspect_subs.py pull
```
N100 의 `bot.sqlite3` (sqlite3 `.backup` 으로 WAL-safe) + `output/poll_state/*.json` + `configs/*.json` 을
`output/snapshot/` + `configs.snapshot/` 으로 미러. **dev 의 git tracked `configs/` 는 절대 안 건드림** —
snapshot 은 별도 디렉토리(읽기 전용 사본). N100 IP 가 바뀌었으면 `DEPLOY_HOST=aaaa@<새IP>` 환경변수.

### 2. 미해결 신고 목록
```
python scripts/inspect_subs.py reports                  # open 만 (기본)
python scripts/inspect_subs.py reports --status all     # 종결된 것까지
python scripts/inspect_subs.py reports -v               # 각 신고 풀 inspect (진단까지 포함, 길다)
```
한 건씩 골라 처리. 우선순위 정할 때 같은 slug 의 신고가 여럿이면 그게 더 시급(많은 사용자에게 영향).

### 3. 한 건 풀 진단
```
python scripts/inspect_subs.py inspect report <N>
```
출력 섹션 순서대로 본다:
- **신고 #N** — issue 텍스트(사용자가 자연어로 호소한 증상)
- **진단** — `bot.inspector.diagnose()` 의 휴리스틱 태그들. 🔴error → 🟡warn → ℹ️info 순.
- **최근 register 잡** — 사용자가 원래 제출한 URL · article_url · register.py 출력 tail. `subscriptions.url` 은 UPSERT 라 마지막 /watch URL 이라 *원래 등록 시 URL* 을 보려면 여기를 본다.
- **구독 행** — DB 상의 (user, slug, target, filter) 들.
- **config** — `configs/<slug>.json` 파싱본. `strategy` / `kwargs` / `_recognized_platform` / `list.fields` 가 어떻게 잡혔는지.
- **state** — `output/poll_state/<slug>.json`. `n_baseline` / `last_poll_at` / `consecutive_breakage` / `config_path`.

진단 태그별 의미 (코드: `bot/inspector.py::diagnose`):
- `auto_register_failed` (error) — `.FAILED.json` 마커. *등록 자체* 가 실패 → 이 스킬 대상 아님. hand-config 모드 B 로.
- `config_missing` (error) — config 파일 없음. 보통 N100 에 슬러그는 있는데 파일이 다른 절대경로(state 의 `config_path`)에 있는 경우. snapshot 이 최신인지 의심.
- `query_kwargs_mismatch` (warn) — **신고의 가장 흔한 원인.** 사용자가 `?category=...` / `?type=...` / `?tab=...` 같은 query 가 있는 URL 로 /watch 했는데 config.kwargs 가 비어있음. recognizer 가 그 query 를 무시한 것. *해당 recognizer 의 builder 가 query 를 파싱하지 않는다*.
- `query_kwargs_keys_disjoint` (info) — query 키와 kwargs 키가 한 개도 안 겹침. 변환된 형태일 수도, 무시된 것일 수도. 확인 필요.
- `breakage_signal` (error) — `consecutive_breakage>0`. 폴링이 연속 깨짐. selector drift / 사이트 구조 변경 의심.
- `stale_poll` (warn) — 24h 넘게 폴링 안 됨. N100 down 또는 timer 깨짐. **이건 사이트별 문제 아님** — 운영 메모 §7 의 systemd 확인부터.
- `empty_baseline` (info) — 등록 당시 글 0건. 어댑터 selector 가 잘못 잡혔거나 사이트가 진짜 비었거나.
- `never_delivered` (warn) — 구독 ≥7일 + deliveries 0건. 필터가 너무 빡세거나 사이트 자체가 신글이 거의 없거나 폴링 깨짐. fetch 시뮬과 함께 봐야 구분 가능.

### 4. fetch 시뮬로 현재 동작 확인
```
python scripts/inspect_subs.py fetch <slug> -n 5
```
스냅샷의 config 로 어댑터를 *지금 실제로* 돌려 top N 글을 가져온다. 출력은 inspect 결과 + 그 글 목록 + 진단 갱신(`fetch_sim_empty` / `fetch_sim_same_id` 신호 추가). 신고 issue 와 대조:
- "공식 탭 글이 와야 하는데 일반 게시판 글이 와요" → fetch 결과의 카테고리·post_id 가 *어느 탭* 의 것인지 본다.
- "본문이 비어요" → fetch_sample 의 post_id 한 개로 `python -c "import asyncio,json; from engine import make_adapter; ..."` 같은 별도 스모크는 추가 작업.

### 5. 원인 분류 → 수정

#### 5a. recognizer 가 query/path 일부를 무시 (대표 사례: arca-tab `?category=`)
- 진단: `query_kwargs_mismatch`
- 코드 위치: `engine/recognizers/<plat>.py` 의 `_build()`. 거기서 `urllib.parse.parse_qs(urlsplit(url).query)` 로 파싱해 의미 있는 키만 `kwargs` 에 추가. 모르는 query 키가 섞여 있으면 `None` 반환(probe/gemini 경로로 폴백 = 안전 디폴트).
- 어댑터가 그 kwarg 를 받는지 확인: `adapters/<plat>.py` 의 `__init__` signature.
- **회귀 방지 테스트 추가**: `tests/recognizers/test_<plat>.py` 의 `run()` 에 케이스. 같은 패턴 = standalone runnable, `run() → list[(name, ok, detail)]`.
- 진단 휴리스틱이 약하면 `bot/inspector.py::diagnose` 에 룰 보강 (예: arca 외 사이트에서도 잘 잡히는 케이스). `tests/inspector/test_diagnose.py` 에 케이스 추가.

#### 5b. 어댑터 selector drift / 본문 추출 깨짐
- 진단: `breakage_signal`, `fetch_sim_empty`, `fetch_sim_same_id`, `never_delivered` + 본문 빔
- 코드 위치: `adapters/<plat>.py` (handwritten) 또는 `configs/<slug>.json` 의 `list.row_selector` / `article.content[].selector` (httpx_html / playwright_html).
- 사이트의 현재 HTML 을 다시 본다: `python -c "import asyncio; from engine import make_adapter; ..."` 또는 probe 재실행. hand-config 모드 A 의 6단계 스모크 패턴 그대로.
- selector 수정 후 fetch 시뮬 다시 → 진단 깨끗해질 때까지.

#### 5c. 사용자 필터가 너무 빡셈
- 진단: `never_delivered` 만 + fetch_sim 은 정상
- 코드 수정 없음. owner DM 으로 사용자에게 "필터 풀어보세요" 안내 + `/unwatch`/`/watch` 다시.

#### 5d. 이미 broken config 가 남아있어 다른 사용자도 같은 결과를 받음
recognizer 를 고쳐도 *이미 만들어진* `configs/<slug>.json` 은 그대로다. `_is_registered(slug)` True 라서
새 /watch 도 재등록을 트리거 안 함. 운영 메모 §7 "강제 재등록" 절차 — N100 에서:
```
ssh aaaa@<lan-ip> 'cd ~/notice-watcher && rm output/poll_state/<slug>.json configs/<slug>.json'
```
그 다음 사용자에게 `/watch <원본 URL>` 재요청 안내. 또는 owner 가 본인 계정으로 재현. 둘 다 안 되면 *worker 큐* 에 register 잡을 직접 enqueue 하는 admin 명령을 추가해야 하는데 — 현재 그건 없다(필요해지면 `bot/admin.py` 에 추가).

### 6. 테스트 + 회귀 smoke
```
python tests/recognizers/test_<plat>.py        # 그 recognizer
python tests/inspector/test_diagnose.py        # 진단 룰
python scripts/probe_smoke.py                  # 전체 회귀(configs validate / heuristic units)
```
모든 PASS 여야 다음 단계.

### 6b. dev박스 로컬 등록·검증 — N100 배포 전 *반드시*
fix 한 코드가 실제로 의도대로 동작하는지 사용자 재 /watch 없이 dev박스에서 직접 확인한다. 사용자가 신고한
*그 원본 URL* 을 통째로 흘려서 fetch_list 결과가 *기대한 탭/카테고리/필터* 의 글로 채워지는지 본다.

**1순위 (안전, 디스크 안 건드림)** — `inspect_subs.py verify`:
```bash
python scripts/inspect_subs.py verify --report <N>      # 신고에서 URL 자동 추출
python scripts/inspect_subs.py verify --url "<원본 URL>"  # URL 직접
```
이건 `engine.recognizers.recognize()` 로 in-memory config 만 만들고 그것으로 `adapter.fetch_list` 돌려
top N 글을 보여준다. `configs/` · `output/poll_state/` *전혀 안 건드림* — 정리 절차 불필요.

출력에서 확인할 것:
- `recognizer: arca-live` 같은 *어느 인식기가 매칭됐는지*
- `kwargs: {"channel": "x", "category": "공식"}` 같은 *수정한 의도가 반영됐는지*
- 글 목록의 `[category]` 컬럼 + 마지막 줄의 **카테고리 분포** — arca-tab fix 검증의 핵심 (`공식=10, -=0` 이면 통과)
- `매칭 안 됨` 이면 fast-path 거부 (unknown query / multi-value 등) — 그게 의도면 통과, 아니면 recognizer 더 손봐야 함

**2순위 (recognizer 가 None 반환 = probe/gemini 경로)** — `verify` 로 검증 불가하니 실제 `register.py` 돌려야 함:
```bash
SLUG=$(python -c "from probe.paths import url_to_slug; print(url_to_slug('<원본 URL>'))")
python scripts/register.py "<원본 URL>"        # configs/<slug>.json + output/poll_state/<slug>.json 생성
python -c "
import asyncio
from bot.inspector import fetch_sim, InspectorPaths
sample = asyncio.run(fetch_sim(InspectorPaths.live(), '$SLUG', n=10))
for p in sample or []:
    print(p['post_id'], (p.get('category') or '-'), repr((p.get('title') or '')[:70]))
"
```

판정:
- 의도대로면 → 7~8(doc·배포) 진행.
- 잘못 나오면 → 5(원인 분류) 로 돌아감. 진단 부족이면 5d 의 broken slug 복구만으론 충분치 않다는 신호.

**2순위 경로** 만 검증 끝나면 dev 의 임시 산출물 정리(commit 안 되게):
```bash
# 신규 사이트면 dev tracked configs/ 에 처음 생긴 거라 git status 에 새 파일로 뜸. 검증용이라 *제거*.
rm -f "output/poll_state/${SLUG}.json" "output/poll_state/${SLUG}.FAILED.json"
# configs/${SLUG}.json 이 *이미 git tracked* 였다면 restore: git checkout configs/${SLUG}.json
# 아니면 untracked 새 파일이라 그냥 rm: rm -f configs/${SLUG}.json
```
※ 이 정리 안 하면 §8 의 `git add -A` 가 검증용 산출물까지 함께 push 함. 의도된 코드 fix 만 stage 되도록.

### 7. doc 갱신
`docs/사이트별 등록 시도 기록.md` 에 항목 추가/갱신: slug · 신고 이슈 · 원인(어떤 recognizer/어댑터 어디) · 수정 내용 · 상태 이모지(✅자동 / 🔧손config / 🧩손어댑터 / ❌FAILED). 다음에 같은 류 신고가 또 들어왔을 때 빠르게 매칭하기 위함.

### 8. N100 배포 (`docs/운영 메모.md` §8)
- dev 폴더 = repo dev clone. 바뀐 파일 stage:
  - `engine/recognizers/<plat>.py` (recognizer fix)
  - `adapters/<plat>.py` (어댑터 fix 시)
  - `bot/inspector.py` (진단 룰 추가 시)
  - `tests/...` (회귀 케이스)
  - `docs/사이트별 등록 시도 기록.md`
- `git add -A; git commit -m "<요지>"; git push origin main` (commit 메시지 끝에 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`)
- N100 배포:
  ```
  ssh aaaa@<lan-ip> 'cd ~/notice-watcher && git pull --ff-only && systemctl --user restart notice-bot.service'
  ```
  - `requirements.txt` 변경 있었으면 앞에 `.venv/bin/pip install -r requirements.txt &&`.
  - **새 어댑터/엔진 import 가 있었다면 봇 재시작 필수** (hand-config §9 와 같음).
  - **broken slug 강제 재등록 (5d) 이 필요했으면** `git pull` *뒤에* `rm output/poll_state/<slug>.json configs/<slug>.json` *그 후* 봇 재시작.

### 9. 신고 종료
Discord 에서 owner 계정으로:
```
/admin resolve report:<N> note:<짧은 수정 설명>
```
DB 의 `reports.status` 를 `resolved` 로 마킹 + `resolved_note` 기록.

CLI 에서 처리하려면 (admin guild 에 없을 때 등) — 아직 `scripts/inspect_subs.py` 에 resolve 서브커맨드는 없음.
필요해지면 추가하면 됨(현재는 owner 가 Discord 에서 한 줄). 임시로 N100 에서 sqlite 직접:
```
ssh aaaa@<lan-ip> 'cd ~/notice-watcher && .venv/bin/python -c "from bot import db; c=db.connect(); print(db.resolve_report(c, <N>, \"수정 내용\"))"'
```

### 9.5. case_runs DB row (필수, 매 신고 처리)
dev 박스에서 `docs/case_runs DB 계획.md` 의 audit row 박음 — 코드 변경 X (재현 안 됨 / 사용자 오해) 도:
```bash
python scripts/case_log.py log \
  --slug <신고 slug> --skill report-triage \
  --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \
  --reason "<1-3줄 — 신고 issue + 진단 + 처리 결과>" \
  [--fix-layer <F>] [--failure-keys <key>] [--case-md-slug <slug if 만들었으면>]
```
outcome 분류 (hand-config 와 동일):
- `improved` — recognizer/엔진 fix 로 코드 일반화 + 효과
- `handcrafted` — 손-config 또는 어댑터 fix 로 그 사이트만
- `no_change` — 재현 안 됨 / 사용자 오해 / 이미 작동
- `rejected` — 정책상 처리 안 함 (예: 사이트가 차단 정책 변경)
- `rejected_with_policy` — no-change 인데 영구 기록 가치
- `error` — 처리 도중 미완

dashboard `/cases` 에서 표시. 잊어도 push 차단 X (~10% gap 수용).

### 10. (선택) 신고자에게 통보
봇에 그런 명령은 없음. owner 가 DM 으로 직접 알리거나, 사용자가 다시 `/watch` 하기 전까진 모름.
필요하면 `bot/admin.py` 에 `/admin notify report:<N>` 추가 (resolved_note 를 신고자 DM 으로) — 현재 미구현.

---

## 자주 만나는 패턴 (사례집)

### 패턴 1: 채널 탭/카테고리 URL 의 query 무시 (2026-05-14 arca-tab)
- 증상: 사용자가 `https://arca.live/b/X?category=Y` 로 /watch → 일반 게시판 글이 옴
- 진단: `query_kwargs_mismatch` (URL query 있는데 config.kwargs 비어있거나 매핑 누락)
- 원인: `engine/recognizers/arca_live.py` 의 `_build()` 가 query 안 보고 channel 만 캡처
- 수정: `parse_qs` 로 `category` 추출 → `kwargs.category`. 알 수 없는 query 키 있으면 None 반환 (fast-path 거부, probe 경로로 폴백). multi-value 도 None.
- 어댑터 확인: `adapters/arca.py` 는 이미 `category` kwarg 받음 — 어댑터 수정 불필요.
- 회귀 테스트: [`tests/recognizers/test_arca_live.py`](../../tests/recognizers/test_arca_live.py).
- broken 기존 구독 복구: 5d 절차.

### 패턴 2: 사이트 selector drift
- 증상: 한 사이트만 며칠째 새 글이 없다고 느끼거나, 본문이 빔
- 진단: `breakage_signal` + `fetch_sim_empty` 또는 `fetch_sim_same_id`
- 원인: 사이트가 HTML 구조 바꿈
- 수정: 어댑터 또는 config 의 selector. hand-config 모드 A 패턴.

### 패턴 3: 필터가 너무 빡셈
- 증상: 새 글은 분명 있는데 알림이 안 옴
- 진단: `never_delivered` 만 떴고 fetch_sim 은 정상 글 목록 반환
- 원인: 사용자가 준 자연어 filter 가 Gemini 분류에서 거의 모든 글을 reject
- 수정 없음. 사용자에게 필터 풀어 재 /watch 안내.

### 패턴 4: 사이트 자체가 비공개/로그인 필요로 변경
- 증상: 본문이 비거나 401/403
- 진단: `never_delivered` + fetch_sim 본문 0자
- 원인: 어댑터가 401/403 을 받고 본문을 비워 반환(정책상 우회 금지)
- 수정: 사용자에게 안내. storage_state 로 로그인 세션 주입은 별도 절차(`docs/사이트별 구현 방침.md`).

---

## 주의
- snapshot 디렉토리(`output/snapshot/`, `configs.snapshot/`)는 .gitignore — 절대 commit 안 함. dev tracked `configs/` 와 분리됨.
- `bot/inspector.py` 에 새 진단 룰 추가하면 `tests/inspector/test_diagnose.py` 에 케이스 같이 추가. 안 그러면 silent 회귀 위험.
- 한 신고를 처리하면서 *recognizer/어댑터 일반화* 가 가능하면 같은 사이트의 다른 게시판이 자동으로 풀린다 — hand-config 와 같은 원리. 모드 B 와 평행하게 인식기/어댑터 보강을 1순위로.
- `/admin inspect`, `/admin fetch` 는 chromium 을 부르는 명령(`fetch` 만) — 봇 프로세스의 이벤트 루프를 잠시 점유한다. 폴링과 동시 실행 시 chromium 락 경합 가능. 큰 문제는 아니지만 인지.
- 신고 자체에 민감 정보(사용자 토큰/세션 등)는 안 들어가게 — `/report issue` 는 owner DM 으로 직접 가는데 markdown escape 는 inspector 가 code-fence 로 처리. 그래도 issue 내용은 *사용자가 쓴 그대로* 라 사회공학 표시 (@everyone 등) 들어와도 owner DM 에는 의미 없음.
