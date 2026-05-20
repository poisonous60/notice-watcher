---
name: hand-config
description: >-
  notice-watcher 의 자동 등록 실패 사이트(triage 큐)를 진단·해결·N100 배포하는 워크플로우.
  사용자가 "FAILED 큐 처리", "triage", "이 사이트 등록", "손 config 작성", "config 만들어줘" 라고 할 때.
  진단 분기에서 **가능하면 자동 파이프라인 자체(probe 휴리스틱·인식기·schema) 개선**으로 같은 패턴이
  다시 안 들어오게 하는 게 1순위, 손-config/손어댑터는 그게 불가능할 때만.
  이 프로젝트 (`poisonous60/notice-watcher` 의 dev박스 clone) 전용.
---

선언적 config (JSON) 로 게시판 수집. `register.py` 가 probe + LLM 으로 config 자동 생성, 실패 시 `output/poll_state/<slug>.FAILED.json` + `output/triage_queue.jsonl` 두 곳 흔적. 이 스킬이 dev 박스에서 진단·해결·N100 배포. **추측 X — 각 단계 산출물 확인하며 순서대로.**

## 먼저 펼쳐 볼 것 (해당 단계에서 필요한 만큼)
- `engine/config_schema.py` 상단 docstring — config 스키마 (최우선 근거).
- `docs/config 기반 엔진 가이드.md` — 전략(httpx_html/httpx_json/playwright_html/handwritten)·실행·폴링.
- `docs/config 자동생성 실패 케이스.md` — `[FAIL] <체크>` 분류. **진단의 기준**.
- `docs/사이트 어댑터 추가 가이드.md` — 손어댑터 절차.
- `docs/운영 메모.md` §1~3, §8 — N100 SSH/IP/venv/systemctl, 배포 사이클.
- `engine/recognizers/` — 알려진 플랫폼 URL 인식기. register.py 가 probe 전에 `recognize(url)` 먼저. 매칭 시 즉시 config 만들어 등록 (probe/Gemini 생략). 각 플랫폼은 `<plat>.py` 한 파일 — `NAME` + `PATTERNS=[(re.Pattern, builder), ...]` export, auto-discovery. 현재 목록: `ls engine/recognizers/`.
- 손어댑터 목록: `adapters/__init__.py`.
- 레퍼런스 config: `ls configs/*.json` (strategy 별 1-2개 골라 베끼기).

---

## 0. 진입

기본: 봇 triage 큐 처리 ("FAILED 처리"/"triage"/"이 사이트 등록"). `/preview`·`/watch` 자동 등록 실패한 사이트들.

링크 하나만 들고 온 새 사이트:
- `python -c "from engine.recognizers import recognize; print(recognize('<URL>'))"` — 매칭 시 `register.py "<URL>"` → §5 배포.
- 미매칭이면 `register.py "<URL>"` 1회 — 성공이면 §5, 실패면 `.FAILED.json` 생기니 §1 흐름.

## 0a. batch 사후 처리 우선순위 (drain 완료 후 fail_kind 분포 받았을 때)

`scripts/remote.py batch-register` drain 후 fail_kind 분포(`bot.sqlite3` jobs / dashboard `/jobs` `/candidates`)를 보고 **아래 순서대로** 처리. 2026-05-21 사용자 결정 — 다음 batch 부터 항상 이 우선순위.

1. **bug (rc=-1/-2/-3/-5/-99, `.BUG.json`)** — **무조건 fix**. 최우선. traceback 분석 → bot/scripts/engine 코드 수정 → 테스트 → commit+push+N100 pull+restart → `.BUG.json` clear. hand-config 와 별 카테고리 (bug-fix workflow, CONTEXT.md). batch 의 `register.py 실행 시간 초과(300s)` 류 timeout 도 여기 — 왜 느린지 root-cause.

2. **gate_reject (rc=3, `.REJECTED.json`)** — board_shape / nav_only / single-article 게이트가 **게시판형태 글을 오탐 거부**하는 게 현재 약점 (단일게시판·글없음 vs 게시판형태 구분 부정확). 대부분 진짜 게시판인데 거부됨 → 게이트 휴리스틱 고쳐야 함. **단 사용자가 case 확인 후 알려줌** — 임의로 "의도된 거부"라 신뢰 X, 사용자 신호 대기. 받으면 probe 휴리스틱(2c/2d) 개선으로 false-positive 차단.

3. **capability_blocked (rc=5, `.FAILED.json`)** — captcha/anti-bot/cloudflare 차단 = **능력 부족(정책 아님)**. `register.py` 가 자동으로 rc=5+FAILED 박음 (2026-05-21 policy_reject 에서 split). stealth/anti-detection 어댑터로 재도전 (§2e + docs/크롤링 지침.md §6 stealth 허용). `policy_reject`(rc=2 LOGIN_REQUIRED)·`url_dead`(rc=4 죽은 URL)와 **구분** — 이 둘은 의도된 거부, 작업 X.

4. **gen_fail (rc=1, `.FAILED.json`)** — 기존 hand-config §1~§5 그대로 (진단 → 손-config 또는 probe/prompt 개선).

`policy_reject`(rc=2)·`url_dead`(rc=4) = 작업 대상 아님 (정상 거부). 분포 확인은 `python scripts/triage.py list` + dashboard.

## 0b. preflight — 이미 고쳐졌나 / 옆 작업이 큐를 stale 화했나

§1 진단 진입 *전*, 각 큐 slug 에 대해 두 검사 강제. 본 검사 = 자가개선 인프라 (CLAUDE.md §6 + ADR 0003) 의 부산물 — prompt / engine / probe / recognizer 옆 작업이 큐 진입 후에 일어났으면 큐가 *옛 상태* 일 가능성. SKILL 이 그 가능성 인지 안 하면 *이미 회복 가능한 사이트에 손-config 작업 박는 낭비* 발생 (CLAUDE.md §8a 의 영구 게이트 정신).

### (a) stale 큐 검사 — configs/<slug>.json 또는 손-adapter 이미 존재?

```bash
# configs/ 존재 확인
test -f "configs/<slug>.json" && python scripts/register.py --config "configs/<slug>.json"

# 또는 recognizer 매칭 확인
python -c "from engine.recognizers import recognize; print(recognize('<URL>'))"
# 매칭이면: python scripts/register.py "<URL>"
```

성공 → 큐 자동 정리 → 본 slug **종료** (§1 진단 skip). 실패 → (b) 또는 §1 진입.

### (b) 옆 작업 회복 검사 — 큐 진입 후 prompt/engine/probe 변경 있나?

```bash
# FAILED.json 의 failed_at 추출
failed_at=$(python -c "import json; print(json.load(open(r'output/poll_state/<slug>.FAILED.json',encoding='utf-8'))['failed_at'])")

# 그 이후 영향 영역 commit 있나
git log --since="$failed_at" --oneline -- prompts/ engine/ probe/ generate/ engine/recognizers/
# uncommitted 변경도 jurisdiction (현 dev 세션의 작업)
git status --short -- prompts/ engine/ probe/ generate/ engine/recognizers/
```

둘 중 하나라도 있으면:
- probe artifact (`output/probe/<slug>/`) 존재 → `python scripts/register.py --reuse-probe "<URL>"` (LLM 만 재호출, fetch 0 추가)
- artifact 없음 (큐가 *FAILED.json 만* 가져온 경우 — snapshot copy 등) → `python scripts/register.py "<URL>"` (full probe + 생성)

성공 → 큐 정리 + §1 skip. 실패 → §1 진입.

### (a)+(b) 모두 fail 시 → §1 진단 정상 진입

본 preflight 결과는 §2 진입 전 강제 인용 6번 으로 인용 (skim 방지). 형식 = `preflight: <a-hit|b-hit|miss> — <slug> [<commit-sha-if-b-hit>]`.

---

## 1. 가져오기 + 진단

```
python scripts/triage.py pull --skip-later   # N100 → 로컬 (FAILED.json + triage_queue.jsonl + 실패 slug 의 probe/); dashboard '나중에' 토글 slug 제외
python scripts/triage.py list --skip-later   # 받아온 실패 목록 표 (Later 숨김)
python scripts/triage.py show <slug>         # 그 slug 의 .FAILED.json + 요청자 + probe digest (diagnosis / list_candidates / HAR slice 자동 출력)
```

`--skip-later` 가 제외하는 slug 는 dashboard `/triage/failed` 의 '나중에' 토글로 결정 (`output/triage_later.json`, dev box only). 후순위로 미뤘다는 신호 — 같은 dev 박스에서 dashboard 와 동일 큐 공유. Later 라도 명시적으로 처리하고 싶으면 `show <slug>` 또는 인자 빼고 호출.

호스트는 Tailscale MagicDNS `<user>@<host>` (LAN/외부 모두 동작). LAN IP `aaaa@<lan-ip>` 도 집에서는 OK. 다른 호스트 필요시 `DEPLOY_HOST=aaaa@<…>` 환경변수.

`show` 출력의 `last_feedback`(=`[FAIL] <체크>`), `last_config`(자동 생성된 마지막 시도 — selector/path 한두 개만 고치면 될 때도 많음), `output/probe/<slug>/` 의 `summary.txt`·`list_candidates.json`·`article_candidates.json`·`traffic.har`·`diagnosis.json` 을 본다. `docs/config 자동생성 실패 케이스.md` 의 §번호에 매칭해 원인 분류.

**진단 직후 — 두 트랙 동시** (한쪽이 다른 쪽 막는 게이트 X):
- **트랙 A** (사용자 향 — 사이트 즉시 작동): 2a~2d 중 매칭 있으면 그게 해결 수단, 없으면 2e (손-config/손어댑터). 항상 결과물 있음 (작동 또는 거부 마커).
- **트랙 B** (미래 향 — 같은 패턴 재발 차단): 손-config 으로 끝낸 케이스도 의무 검토. 후보 — 2a (인식기 PATTERNS 한 줄 추가 = 플랫폼 config, handcrafted), 2b (`first_article_url` 잘못 잡힘 → `--article-url` 재시도, 추론 개선), 2c (probe artifact 에 신호 있는데 휴리스틱화 안 됨, 추론 개선), 2d (probe 자체 오작동, 추론 개선).

각 후보 한 줄 점검 (`X — 이유` 또는 `O — 자리`). 매칭 시 같은 PR. 0건이면 case body 에 이유 1줄.

예시: `host_scholar-google-_scholar_706d9c49` (commit `0b130b2`) — 트랙 A 손-config + 트랙 B (C) `probe/extract.py:list_row_external_host` + (D) `generate/validate.py:_external_host_hint`. 동시.

### §2 진입 전 — 강제 인용 (skim 방지)

`triage.py show <slug>` 출력 받은 *바로 다음 assistant 메시지* 에서, **§2 분기에 해당하는 코드 변경 (Edit/Write — 인식기·probe·prompt·config 손대기 또는 손-config 작성) 보내기 전에**, 같은 메시지 안에 다음 4개 명시 출력해야 함. 인용 없이 §2 진입 X — 가설 헛디딤(β) 의 직접 차단. (인용과 그 다음 Edit/Write 사이에 추가 Read/Bash 보강은 OK — 단, *4개 인용은 첫 메시지에서 끝* 내고 그 뒤에 보강.)

1. **`last_feedback` 첫 `[FAIL]` 줄** (`triage.py show` 출력에서 verbatim)
2. **`diagnosis.json` 의 `verdict`** (digest 에 표면화됨)
3. **`docs/config 자동생성 실패 케이스.md` 매칭 §번호** + 1줄 근거
4. **분기 후보 (2a~2e)** + 그 선택 1줄 이유
5. **누적 cross-check** — 진단한 failure_keys 각각에 대해 `python scripts/cases_index.py query --failure-key <key> [--failure-key <key2> ...] --json` 1회 호출 + JSON 결과 인용. 같은 진단의 root-cause 신호 (예: `static_vs_headless`, `diverging_first_article`) 가 case body 에 흔적 있으면 `--signal "<regex>"` 도 동시 호출. 그리고 `python scripts/cases_index.py query --deferred --json` 으로 deferred 후보 트리거 상태 확인. **한 label 의 `track_b_trigger=true` 면 트랙 B 진입 강제 — deferred 보류 불가, 같은 PR 에 휴리스틱·인식기·prompt 박음**. 0건이면 명시 ("누적 0건 — 첫 사례, deferred OK").
6. **preflight 결과** (§0b) — `preflight: <a-hit|b-hit|miss> — <slug> [<commit-sha-if-b-hit>]`. a-hit 또는 b-hit 면 §2 진입 자체 X (이미 회복) — 인용 1줄 + 종료. miss 만 §2 진입. 본 인용 = §0b 강제 실행 증명. preflight 안 돌렸으면 *그 자체로 SKILL 위반*.

artifact 없는 §0 신규 진입 (link 만 받은 첫 시도) 케이스는 예외 — `[§0 entry, no artifact yet]` 한 줄 명시 후 §0 절차로. 5번 (누적 cross-check) 도 skip (failure_keys 없음).

`show` 가 자동으로 prepend 하는 digest (diagnosis / list_candidates / HAR) 가 1~4 인용 source. 5 는 `cases_index.py query` 출력 source. 그 외 정보 필요하면 `Read` 로 보강 가능하지만 위 5개는 *항상* 인용해야 함.

## 2. 분기 — 위에서부터 차례로 따져 첫 매칭 (2a~2d 가 2e 보다 우선)

### 2a. 이미 알려진 플랫폼 / 또는 인식기만 넓히면 됨

`python -c "from engine.recognizers import recognize; print(recognize('<URL>'))"`.
- 매칭되면 → 그냥 `python scripts/register.py "<URL>"` (이 실패는 인식기 추가되기 전 거였거나 봇이 옛 코드일 때 난 것).
- 매칭은 안 되지만 같은 플랫폼의 다른 게시판이 이미 손어댑터/손config 로 있으면(예: 다음카페 다른 게시판인데 인식기가 그 URL 형태를 아직 안 받음) → `engine/recognizers/<해당-플랫폼>.py` 의 `PATTERNS` 에 그 URL 형태를 받는 패턴 추가/확장 → `register.py "<URL>"`. (그 플랫폼 전체가 자동으로 풀린다.)

### 2b. probe 가 '첫 글'을 잘못 집음 — `--article-url` 재시도

`list_candidates.json` 의 `first_article_url` 이 사이드바/메뉴 링크일 때. 보통 `[FAIL] posts_nonempty` 나 `[FAIL] article_body_len` + `[warn] matches_probe_first_article` 동반.

→ 그 게시판의 진짜 글 하나 URL 을 찾아서 `python scripts/register.py "<목록URL>" --article-url "<글URL>"` (probe 산출물 재사용하려면 `--reuse-probe` 도). first_article_url 교정 + 그 글페이지 render+HAR re-probe + 강한 hint 로 처음부터 재생성. 성공하면 손작성 없이 끝 → §5 배포.

### 2c. probe 산출물에 *이미 신호 있는데* 휴리스틱화 안 됨 — 휴리스틱 추가 (손 config 보다 우선)

LLM 이 raw HTML/HAR 보고 4회 retry 후 fail — 신호가 `diagnosis.json`/`list_candidates.json`/HAR 에 있는데 안 뽑아서. 미래 같은 패턴 사이트도 자동 처리됨.

기존 신호 단일 진실원: `probe/_contract.py:_ARTIFACTS` 의 `_ContractField.note`. 새 휴리스틱 박기 전 *거기 없는 카테고리* 인지 확인.

휴리스틱화 가치 카테고리:
- 페이지에 박힌 fact (URL/ID/헤더/메타) 인데 현 휴리스틱이 안 추출
- LLM 이 raw 보고 자주 틀리는 신호 (login gate · paywall · SPA shell · pagination meta · 본문 selector)
- preflight 거부 가능한 영구 차단

셋 다 아니면 휴리스틱 X (LLM raw 로 직접 봐도 충분).

처리:
1. `probe/extract.py` 등에 새 `@heuristic` 함수 — 입력 = 기존 artifact, *추가 fetch 금지* (순수). 출력 = `diagnosis.json`/`list_candidates.json` 명시 키.
2. **활용 자리 동시 박기**:
   - LLM 활용 → `prompts/config_writer.system.txt` 에 키 설명 한 줄 + `_PROMPT_REQUIRED_KEY_PATHS` 등록.
   - preflight 거부 → register.py 가 키 보면 즉시 fail (LLM 호출 skip, 4회 retry 비용 0).
   - recognizer 후처리 → recognize 결과를 probe digest 와 merge 단계 신설 필요 (현재 X — F-layer).
3. 영구 거부 마커 = `.REJECTED.json` + `bot/site_ops.py:is_registered` 가 봄 (별 PR).
4. 휴리스틱 추가 규칙 (↓ §4) — fixture·contract·smoke 통과.

### 2d. probe 가 부족/오작동 — probe/ 수정

글페이지 render 가 잘못된 페이지를 열었다, HAR 가 비었다, list_candidates 가 명백한 row 를 못 잡았다 등. `probe/`·`scripts/probe.py` 를 고칠 수 있나 본다. 고치면 재-probe 후 `register.py "<URL>" --reuse-probe` (또는 그냥 `"<URL>"`).

휴리스틱·산출물 수정 규칙: ↓ §4.

### 2e. 자동 파이프라인이 진짜 안 닿는 한계 — 손 config 또는 손어댑터

handwritten 만 가능: 클릭/스크롤로만 글이 뜨는 SPA, 강한 anti-bot, 비공개판이지만 *사용자가 storage_state 로그인 경로 제공 의사 있음*, 본문이 클라이언트 라우트라 server-render 본문 없음, 등. probe 가 어떤 신호도 휴리스틱화할 만하지 않은 진짜 코너 케이스.

`last_config` 에서 selector/path 한두 개만 바꾸면 되는 경우도 많다. 손 config 작성 절차 ↓ §3.

## 3. 손 config / 손어댑터 작성 절차 (2e 진입 시)

1. **slug 확정** — `python -c "from probe.paths import url_to_slug; print(url_to_slug('<URL>'))"`. config 파일명·state 파일명·doc 항목 모두 이 slug.
2. **probe** — `python scripts/probe.py "<URL>"` (느리면 `--lite`). 이미 있으면 skip.
3. **전략 선택**
   - **이미 그 사이트 손어댑터가 `adapters/` 에 있으면** → 가장 간단. `strategy:"handwritten"`, `adapter:"<클래스명>"`, `kwargs:{...}` 만. (네이버 카페·아카라이브·디시·SKKU 등이 여기.)
   - 정적 HTML 목록 + 정적 HTML 본문 → `httpx_html`. `list_candidates.json`·HAR 로 `row_selector`·각 field selector 작성.
   - 목록 또는 본문이 JSON XHR → 목록이면 `httpx_json`(+`list_path`), 본문이면 `article.fetch_kind:"json"`(+`data_path`). HAR 에서 API URL·응답 트리 확인.
   - JS 렌더인데 `goto`+networkidle 로 잡힘 → `playwright_html` + `wait_selector`.
   - 클릭/스크롤 후에야 뜨거나 Cloudflare 챌린지 강함 → `docs/사이트 어댑터 추가 가이드.md` 따라 손어댑터 신규 작성 → handwritten config 로 감쌈.
4. **config 작성** — `configs/<slug>.json`. 필수 키: `version`(1)·`site`·`board`·`strategy`. httpx_*/playwright 면 `list.url_template` + `list.fields.{post_id,title}` 필수. `_source_url` 에 원본 URL. `_note` 에 손작성 이유 한 줄. 레퍼런스 config 베껴 시작.
5. **스키마 검증** — `python -c "import json; from engine.config_schema import validate_config; validate_config(json.load(open(r'configs/<slug>.json',encoding='utf-8'))); print('OK')"`
6. **스모크 테스트** —
   ```
   python -c "
   import asyncio, json; from engine.config_adapter import make_adapter
   c=json.load(open(r'configs/<slug>.json',encoding='utf-8'))
   async def m():
       async with make_adapter(c) as a:
           ps=await a.fetch_list(page=1); print('list', len(ps))
           for p in ps[:3]: print(p.post_id, repr((p.title or '')[:50]), p.published_at)
           if ps: f=await a.fetch_article(ps[0]); print('body chars', len(f.content_html or ''))
   asyncio.run(m())"
   ```
   목록 0건이거나 본문 0자면 config 가 틀린 것 → 4로 돌아간다.
7. **로컬 등록** — `python scripts/register.py --config "configs/<slug>.json"` → `output/poll_state/<slug>.json` baseline. 같은 slug 의 `.FAILED.json`·`triage_queue.jsonl` 항목은 `_save_state` 가 자동 정리.
8. **이게 *플랫폼*이면**(같은 패턴 게시판이 여럿) — `engine/recognizers/<plat>.py` 한 파일 신규 작성 (`NAME` + `PATTERNS=[(re.Pattern, builder), ...]` export; builder 가 이번에 만든 config 와 동형의 dict 를 돌려주게). 비슷한 기존 파일(`reddit.py`, `naver_cafe.py` 등) 참고. auto-discovery 가 새 파일을 자동으로 잡음(기존 파일 수정 X). 같은 플랫폼의 다음 게시판은 `/watch`·`/preview` 만으로 즉시 등록됨. `recognize('<다른 게시판 URL>')` 로 확인. 잘못 매칭해도 fetch_list 0건이면 폴백하니 안전.

## 4. probe 휴리스틱·산출물 수정 규칙 (2c·2d 진입 시)

**새 휴리스틱 함수** (순수, 외부 의존 X):
1. `@heuristic` 데코레이터 (`from probe._heuristic import heuristic`)
2. `tests/probe_heuristics/test_<함수명>.py` unit fixture (`run() -> list[(case_name, ok, msg)]`)
3. `python scripts/probe_smoke.py` 통과 (stage 5 coverage 검증). 빠뜨리면 silent fail.

**산출물 파일/키 추가·변경** — 산출물 키는 `engine/digest.py`·`scripts/register.py`·`prompts/config_writer.system.txt` 가 하드코딩 read → silent fail 진원지. 한 자리에서 막음:
1. `probe/_contract.py:OUTPUT_SCHEMA` 갱신 (`ArtifactContract`: 필수/옵션 키, `type_hint`, 필요 시 `prompt_aliases`)
2. write 측에 `validate_payload("<file>.json", payload, allow_extra=False)` 호출 추가/유지 — `probe/extract.py:write_list_candidates`, `probe/discover.py`, `probe/report.py`, `probe/fetch_headless.py`, `scripts/register.py` 의 article_candidates 분기
3. 키 프롬프트 등장 필요 시 — `_PROMPT_REQUIRED_KEY_PATHS` 에 `(file, key)` 추가 + `prompts/config_writer.system.txt` 에 키 (또는 `prompt_aliases` 자연어) 워드바운더리로 등장
4. 새 산출물 파일 추가 시 — `tests/probe_heuristics/test_contract.py` 의 `output_schema_completeness` expected set 에도 추가
5. `probe_smoke.py` 통과 확인 (stage 1·1b·1c)

## 4b. fail 분류 catalog 갱신 (새 [FAIL] check / 새 gate-reject 메시지 도입 시)

§2c·2d·2e 에서 `register.py`·인식기 코드에 *새 거부 사유 메시지* (예: 새 `[FAIL] foo_bar`, 새 `등록 거부 — …` 패턴) 박았다면 fail 분류 카탈로그도 동기해야 함. 안 하면 dashboard `/jobs` 의 status 셀이 그 사유를 *catalog 미등록* 으로 표시 (gen_fail 의 dynamic passthrough 가 잡지만 hint·label 없음).

절차:

1. `bot/fail_taxonomy.py` 의 `FAIL_CATALOG` 안 해당 `FailKind` 의 `subkinds` 튜플에 `Subkind(...)` 한 줄 추가 — `name`/`label_ko`/`hint`/`match`. 기존 matcher 빌더 (`_fail_check`/`_has_any`/`_rc_eq`) 그대로 사용.
2. `tests/fail_taxonomy/test_classify_fail.py` 의 `CASES` 리스트에 `(name, (status, rc, tail), expect_kind, expect_sub)` 한 줄 추가 — tail 은 실제 `register.py` 가 찍는 라인 그대로.
3. `python scripts/gen_fail_taxonomy_doc.py` 실행 → `docs/fail 분류.md` 자동 재생성. 결과 `git add`.

빠뜨리면 pre-push hook 의 `probe_smoke.py` stage 5 가 차단:
- `test_catalog_completeness.py` — fixed Subkind 가 `CASES` 에 없으면 FAIL.
- `test_doc_drift.py` — catalog 변경 + doc 재생성 안 했으면 FAIL.

dynamic family (`recognizer:*`, `[FAIL]:<check>`) 는 추가 필요 X — 자동 capture (catalog 미등록 이름도 surface).

**dynamic Subkind 위치 규칙** — 각 FailKind 의 `subkinds` 튜플 안에서 의도된 우선순위:

- `gen_fail`: fixed `[FAIL]` 매처들 → `[FAIL]:<check>` dynamic passthrough → 토큰 fallback (`gemini_api`). `[FAIL]` 라인이 있으면 그 이름이 항상 토큰 매처를 이긴다 (구 동작 보존).
- `gate_reject`: `recognizer:*` dynamic 이 **첫째**. recognizer fast-path 의도 — 다른 게이트 메시지가 같이 있어도 recognizer 우선. 새 fixed gate Subkind 는 dynamic 뒤에 박는다.

새 Subkind 추가 시 *어느 위치에 박는가* 가 결과를 바꿈 — declaration order = matcher 순회 순서.

**dynamic capture 승격**: `recognizer:foo_bar` 가 자주 등장하면 fixed Subkind (`name="foo_bar_specific"`, `match=_has_any("foo_bar 특정 토큰", name="foo_bar_specific")`) 로 승격 가능. 그 경우 dynamic 앞에 박아 우선순위 확보 + `CASES` 에 fixture 추가 + doc regen.

## 5. 검증 + N100 배포 (모든 분기 공통)

순서 중요 — `case_log` 의 `commit_sha`/`files_changed` derive 가 *현재 HEAD* + `git diff HEAD~1..HEAD` 라 **반드시 commit + push 뒤에** 호출해야 본 case 의 commit 잡힘. commit 전 호출하면 직전 commit (의 sha + diff) 가 잘못 박힘.

1. `python scripts/probe_smoke.py` 그린.
2. 자가 점검 7-질문 (↓ §6) — 비워도 commit 막진 X, 그저 생각해두는 게이트.
3. `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py --backfill-db output/cases.sqlite3` (frontmatter 기반 row 박힘).
4. (권장) `hand-config-reviewer` subagent 호출 (↓ §7). PASS 받으면. (이 시점 DB row = frontmatter backfill 만 — `case_log log` 는 아직 X.)
5. `docs/사이트별 등록 시도 기록.md` 갱신 (상태 이모지·원인·해결).
6. **commit + push** — 단일 commit 정책 (track A+B 한 묶음). `case_log` 의 `files_changed` derive 가 `git diff HEAD~1..HEAD` 만 봐서 다중 commit 시 첫 commit 미캡쳐.
   - stage: `configs/<slug>.json` + 인식기/휴리스틱/엔진/스크립트/docs
   - `git commit -m "<요지>" --trailer "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"; git push origin main`
   - pre-push hook = probe_smoke 자동, FAIL 시 push 차단. `--no-verify` 금지.

7. **case_runs DB row** (필수, 코드 변경 X 도 — `docs/case_runs DB 계획.md`) — **반드시 step 6 commit + push 후**:
   ```bash
   python scripts/case_log.py log --slug <slug> --skill hand-config \
     --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \
     --reason "<1-3줄>" [--fix-layer <C+D>] [--failure-keys <k1,k2>] [--case-md-slug <slug>]
   ```
   이 시점 HEAD = 본 case 의 commit → `commit_sha` 와 `files_changed` 정확. commit 전 실행하면 stderr 에 `⚠ staged/working tree 변경 있음 — commit 후 호출 권장` 경고만 박고 진행 (derive 부정확 가능). outcome 분류는 §6 step 5 표 참조. 잊어도 push 차단 X (~10% gap). dashboard `/cases` 에서 표시.

8. **N100 배포** (운영 메모 §8 SoT) — `ssh <user>@<host> 'cd ~/notice-watcher && git pull --ff-only && .venv/bin/python scripts/register.py --config "configs/<slug>.json"'`.
   - **`adapters/`·`engine/`·`scripts/notify.py`·`bot/` 변경 시 뒤에 `&& systemctl --user restart notice-bot.service`** — 봇 import 캐시. 안 하면 `make_adapter() ValueError`.
   - `requirements.txt` 변경 시 앞에 `.venv/bin/pip install -r requirements.txt &&`.
   - 확인: `register.py --list` 에 slug 가 `registered`. SSH 안 되면 Tailscale 먼저 (`tailscale status` 로 `n100-noticewatcher` 보이는지) → LAN-only 면 콘솔 `ip a` 로 IP 확인 (운영 메모 §1~2).

8b. **post-fix-cleanup** (영구 게이트 박는 변경 *후*) — `python scripts/triage.py post-fix-cleanup --execute` 호출.
   - **언제**: engine/probe/scripts/register 의 *게이트 로직* 자리 박은 변경 (예: 새 휴리스틱 + `_<gate>_check` + register 게이트 추가). N100 의 옛 FAILED.json 큐가 새 게이트로 자동 cleanup.
   - **언제 X**: 손-config 변경 (configs/ 만) — 게이트 영향 X.
   - 동작: N100 ssh + 각 FAILED.json 의 url 에 대해 `register.py --reuse-probe --gate-only` 호출. rc=2/3 = 게이트 잡힘 → 자동 cleanup (REJECTED + FAILED.json 삭제 + triage_queue prune). rc=6 = no gate match → 수동 작업 필요. rc=7 = artifact 없음 → probe 새 실행 권장.
   - **비용 0 보장** (--gate-only 옵션): probe 새 실행 X · preflight 네트워크 re-probe X · LLM 호출 X. 게이트만 검사.
   - 먼저 `--execute` 없이 호출 = dry-run (dev 박스 snapshot artifact 시뮬레이션, write X) — 예상 결과 확인 후 `--execute`.

9. (자동) `.FAILED.json`·`triage_queue.jsonl` 의 slug 항목은 `register.py` 가 자동 정리.

10. **vocab_candidates 임계 알림** (ADR 0003) — `python scripts/cases_index.py vocab-trigger --silent-if-empty` 호출. 출력:
    - 임계 도달 후보 있음 → `[알림] vocab_candidates 임계 도달: <candidate> = N건 — 알림 누적 M회 — /vocabulary-extension 호출 권장` 표시. 사용자가 보고 결정.
    - 미달 또는 후보 0건 → **silent** (`--silent-if-empty` flag 로 출력 X). backfill 권장 메시지는 사용자 직접 `vocab-trigger` (flag 없이) 호출 시만.
    - 모순 (cross-evidence high+low 공존) → 항상 표시 — 캐시 오염 의심 신호.
    - `output/vocab_alerts.json` 에 history 누적 (후보별 keyed: first_seen/last_seen/alert_count/last_trigger_count) — *지속 알림* (한 줄 알림 까먹음 회피).
    - **자동 호출 X** — agent 가 자체 판단으로 `Skill('vocabulary-extension')` 호출 안 함. 사용자 손-호출 영역.

11. (선택) 요청자 알림 — 봇 명령 X, owner DM 또는 사용자에게 `/watch` 재요청 권유.

큐가 빌 때까지 §1~5 반복.

## 6. 자율 개선 시 자가 점검 (가이드라인, 권장)

probe/prompt/schema/코드 손대기 전 다음 여섯 질문에 답해보면 누더기 위험 줄어든다. case 파일 본문 또는 commit msg 본문에 한 줄 메모로 적어둠 — 강제 X.

1. **어느 자리?** — 픽스를 다음 6 자리 중 하나에 매핑:
   - **(E) schema 거부** — `engine/config_schema.py` 의 validate 룰 강화. config 파일만 보고도 잡힘.
   - **(D) retry feedback** — `prompts/config_writer.retry_skeleton.txt` 또는 `scripts/register.py` 의 feedback 빌더. 실행 결과 패턴 (404/0건/0자) 으로만 잡힘.
   - **(C) probe digest 신호** — `probe/` 의 휴리스틱 추가/수정. probe 가 새 데이터를 *추출* 해야 알 수 있는 사실. **분기 2c 의 자리**.
   - **(B) few-shot** — `generate/prompt.py` 의 `_EXAMPLE_CONFIG_FILES` 또는 `configs/` 의 예제. 패턴이 흔하고 config 형태로 명확할 때.
   - **(A) system 규칙 *추가*** — `prompts/config_writer.system.txt` 에 새 룰 줄 추가. *수정/제거* 는 별도 SKILL `pipeline-rot-review` 영역.
   - **(F) 새 엔진 코드** — `engine/strategies/` / `adapters/` / `engine/recognizers/` 신설 또는 `scripts/register.py` 플로우 변경.

   원칙: **위에서부터 차례로 따져 첫 매칭**. (E)/(D) 로 잡힐 것을 (C)/(A) 에 박지 X. ambiguous 면 비워두고 진행.

2. **이전 케이스 있나?** — `python scripts/cases_index.py query --failure-key <key> [--signal <regex>] [--deferred] [--json]` (Grep 대신 — failure_keys frontmatter 직접 인덱싱, 본문 grep, deferred 트리거 매칭 한 번에). 누적 ≥3 = `track_b_trigger=true` → 트랙 B 진입 강제. 박을 때 어느 자리에 박았나 일관 유지. 다른 자리에 박을 거면 이유 명시. 강제 게이트는 §2 진입 전 (위 §2 진입 전 강제 인용 5번) — 여기 §6.2 는 검토 시 재확인용.

3. **누구 깰까?** — 21+ configs 중 영향 사이트 enumerate. 0개 가능하지만 *왜 0개인지* 한 줄 적기.

4. **검증 그린?** —
   - `python scripts/probe_smoke.py` 그린
   - 영향 사이트 있으면: `python scripts/register.py --config "configs/<영향-slug>.json"` 결과 비교
   - LLM 거동 영향 (C/A/B) 이면: 가장 최근 실패 케이스의 probe artifact 로 `register.py --reuse-probe` 1회 — 산출 config 동등 또는 더 좋은지.

5. **case 파일 + commit msg**:
   - `docs/cases/<slug>.md` frontmatter — 필수: `slug`/`url`/`status` (이모지 + 1줄)/`outcome`/`date`. 선택: `fix_layer`/`failure_keys`/`config_strategy`/`adapters_changed`/`engine_files_touched`/`tags`/`requested_by`.
   - `outcome` enum (canonical, DB 박힘):

     | outcome | 의미 |
     |---|---|
     | `improved` | 추론 개선 — AUTO 의 *generic* 추론(probe 추출·LLM 생성·검증·거부 *분류*)이 **미지 *유형*** 을 dedicated adapter 없이 더 풂 (fix_layer C/E/A/D·거부 필터(recognize_reject)·register 거부 게이트) |
     | `handcrafted` | 수동 config — 자동이 못 푼 패치(진보 X). 단일 config·플랫폼 config(발급 recognizer)·손-adapter. fix_layer 무관(F 여도, **C 여도** handcrafted) |
     | ↑ **C-휴리스틱 함정** | fix_layer C(probe 휴리스틱)라고 자동 improved 아님. 휴리스틱이 *알려진 플랫폼 검출→기존 adapter dispatch* 목적이면 (예: `detect_discourse_platform` → DiscourseAdapter) = 커버리지 확장 = **handcrafted**. improved 는 generic 추론이 *미지 유형*을 새 adapter 없이 풀 때만 (CONTEXT.md 19/21/32줄). 판정 test: "자동 솔버가 *처음 보는 구조 유형*을 더 푸나(improved)? 아니면 *알려진 플랫폼*을 더 많은 URL 형태에서 인식만 하나(handcrafted)?" |
     | `rejected` | 정책 거부 마커 |
     | `rejected_with_policy` | no-change + 영구 기록 가치 정책 결정 |
     | `no_change` | 시도했으나 효과 X (case .md narrative 가치 있을 때만) |
     | `error` | skill 미완 (정상 흐름 X — 사후 박기) |

   - `python scripts/cases_index.py --backfill-db output/cases.sqlite3` — INDEX.md + DB sync.
   - commit msg prefix: `[fix-layer: E|D|C|B|A|F|none] <slug>` + 본문에 §6 1번 매핑 + 7번 일반화 사유.

6. **새 패턴이면 smoke_test fixture 추가했나?** — 새 strategy (F) 면 `probe_smoke.py:REPS` + slug-specific `_stage2_check_digest` 분기. 새 휴리스틱 (C) 면 `tests/probe_heuristics/test_<name>.py`. 기존 수정만은 skip. fixture URL = *진짜로 그 패턴 보여주는* URL 인지 probe 결과로 직접 검증.

7. **트랙 B 매칭 0이면 이유 메모** — §1 의 트랙 B 검토 후보 (2a~2d) 매칭 X 면 case body 에 "일반화 안 되는 이유: <한 줄>" 명시. 미래 2번째 케이스 들어왔을 때 즉시 알아채는 비용 절감. — *휴리스틱 후보가 떠올랐지만 보류했나*: 한 줄 `docs/cases/_deferred_heuristics.md` 에 append (format 그 파일 상단). 트리거 도달해 박을 때 그 줄 삭제 + commit msg "deferred_heuristics 제거: <후보명>".

8. **어휘 (engine strategy / source / transform) 후보가 떠올랐나?** — handwritten 분기 (§2.2e) 진입 시 또는 어휘 한계 명백할 때: 이 case .md frontmatter 에 `vocab_candidates: [{candidate, confidence, evidence, reasoning, analysis_date, deferred: true}]` 항목 추가. ADR 0003 의 평가는 *vocabulary-extension SKILL* 의 책임 — 여기서는 *분해 + append 만*. 캐시 entry 형식:
   ```yaml
   vocab_candidates:
     - candidate: click_pagination       # 후보 이름 (스네이크)
       confidence: med                   # high|med|low
       evidence:                          # 코드 path (재검증 source)
         - adapters/daum_cafe.py:42-67
         - case_feedback: "더보기 버튼 존재, [FAIL] posts_nonempty"
       reasoning: "더보기 클릭 루프 — playwright_html.pagination 에 추가 가능"
       analysis_date: 2026-05-18
       deferred: true
   ```
   confidence 가이드: `high` = 어휘 한계 확실 + 코드로 명확, `med` = 가능성 있음, `low` = 의문 (다른 해석 가능). 모르겠으면 low. 박기 X = 적지 X.

위 답 없어도 commit 막지 X — 진짜 검증은 reviewer subagent + pre-push hook.

## 7. 자가 review (commit 직전 — 권장)

**현재 reviewer backend: `codex`** — 전환은 §7b.

코드 변경 또는 손-config 변경 1+ 파일 **commit 직전** reviewer 호출. main thread 가 `probe_smoke`·`case_log query` 실행 결과 prompt 에 박음.

순서: §5 step 3 cases_index `--backfill-db` 후 (= DB 에 frontmatter row 박혔음) → step 4 reviewer → step 6 commit + push → step 7 `case_log log`. **case_log log 는 commit 후** — commit_sha 정확. reviewer 가 보는 row 는 frontmatter backfill row 만 (≈ case .md frontmatter 사본 — 일치성 검사용).

### 7a. 호출 (active backend = codex)

main thread 는 단일 `Bash` 로 codex-companion `task` 호출. `--write` 미부착 = read-only sandbox (review-only 적합).

```python
case_row_json = Bash('python scripts/case_log.py query --slug <slug> --recent 1 --format json')
probe_smoke_out = Bash('python scripts/probe_smoke.py')  # stdout + exit code 캡쳐
diff_out = Bash('git diff HEAD')

# rubric + context 를 한 prompt 에 박음. heredoc 으로 multi-line 안전 전달.
review_prompt = f'''너는 notice-watcher 의 hand-config 변경 reviewer 다.

# fix-layer 6 자리
- E (schema 거부): engine/config_schema.py validate 룰
- D (retry feedback): prompts/config_writer.retry_skeleton.txt 또는 scripts/register.py feedback 빌더
- C (probe digest 신호): probe/ 휴리스틱 추가/수정 → digest 새 키
- B (few-shot): generate/prompt.py 의 _EXAMPLE_CONFIG_FILES 또는 configs/ 예제
- A (system 규칙 *추가*): prompts/config_writer.system.txt 새 룰 줄 추가만. 수정/제거는 pipeline-rot-review 영역
- F (새 엔진 코드): engine/strategies/ / adapters/ / engine/recognizers/ / scripts/register.py 플로우

원칙: 위에서부터 차례 (E > D > C > B > A > F).

# 검증 항목 (8 개) — 하나라도 FAIL 이면 전체 FAIL

1. case 파일 존재 + 필수 frontmatter (slug/url/status/date)
2. fix_layer 정합성 — declared layer 와 변경 파일 세트 일치
3. 회귀 검증 흔적 — case body 에 "회귀 검증" 또는 동등 결과 / 영향 0개 면 이유 명시
4. prompt 수정 종류 — config_writer.system.txt 는 *추가* 만, 수정/제거 FAIL
5. 외부 검증 — probe_smoke 출력에 FAIL 또는 exit≠0 있나
6. docs/cases/INDEX.md 동기화 — cases_index.py 실행 흔적
7. 새 strategy → scripts/probe_smoke.py 의 REPS 에 fixture entry + _stage2_check_digest 분기 추가
8. 새 @heuristic → tests/probe_heuristics/test_<name>.py fixture 추가

# case_runs row 추가 검증
- row=[] 면 cases_index --backfill-db 잊음. PASS but warn.
- row 의 fix_layer/failure_keys/outcome 가 case .md frontmatter 와 일치? 모순이면 FAIL.
- row 의 commit_sha=null 정상 (commit 전이라 — step 7 의 case_log log 가 commit 후 보강).

# 출력 형식 (엄격)
PASS
또는
FAIL
- 항목 N: <위반 한 줄>
- 항목 M: <위반 한 줄>

작문/해설/추천 X. 위반만.

---
## 변경 diff
{diff_out}

## case 파일
[docs/cases/<slug>.md frontmatter + body — main thread 가 Read 로 박음]

## probe_smoke 결과
{probe_smoke_out}

## case_runs row (frontmatter backfill — commit_sha=null 정상)
{case_row_json}

## (선택) 영향 사이트 손-실행
[register.py --config 출력 — 있으면]
'''

result = Bash(f'''node "C:/Users/poiso/.claude/plugins/marketplaces/openai-codex/plugins/codex/scripts/codex-companion.mjs" task "$(cat <<'EOF'
{review_prompt}
EOF
)"''')
```

FAIL → **사용자에게 보고**. 자동 재호출 X. 사용자가 픽스 결정.

### 7b. backend 전환 — claude agent 로 복귀 (현재 비활성)

> 이 sub-section 은 **사용 X**. codex 다운/쿼터 또는 사용자 명시 요청 시에만 §7a 와 swap.
> 전환 절차: §7 상단의 "현재 reviewer backend: `codex`" → `claude` 로 변경 + §7a 의 Bash 호출 블록을 아래 archive 된 `Agent(...)` 블록으로 교체.

`.claude/agents/hand-config-reviewer.md` 가 fallback 으로 유지됨 — sonnet 모델 + 동일 rubric 내장.

<details>
<summary>archive 된 claude agent 호출 (활성화 시 §7a 와 swap)</summary>

```python
case_row_json = Bash('python scripts/case_log.py query --slug <slug> --recent 1 --format json')

Agent(subagent_type='hand-config-reviewer', model='sonnet', prompt=f'''
  ## 변경 diff
  [git diff HEAD]
  ## case 파일
  [docs/cases/<slug>.md frontmatter + body]
  ## probe_smoke 결과
  [stdout + exit code]
  ## case_runs row (frontmatter backfill — commit_sha=null 정상)
  {{case_row_json}}
  ## (선택) 영향 사이트 손-실행
  [register.py --config 출력]

  PASS/FAIL. 추가 검증:
  - row=[] 면 cases_index --backfill-db 잊음. PASS but warn.
  - row 의 fix_layer/failure_keys/outcome 가 case .md frontmatter 와 일치? 모순이면 FAIL.
  - row 의 commit_sha=null 정상 (commit 전이라 — step 7 의 case_log log 가 commit 후 보강).
''')
```

</details>
