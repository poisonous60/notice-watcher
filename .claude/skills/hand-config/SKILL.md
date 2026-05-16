---
name: hand-config
description: >-
  notice-watcher 의 자동 등록 실패 사이트(triage 큐)를 진단·해결·N100 배포하는 워크플로우.
  사용자가 "FAILED 큐 처리", "triage", "이 사이트 등록", "손 config 작성", "config 만들어줘" 라고 할 때.
  진단 분기에서 **가능하면 자동 파이프라인 자체(probe 휴리스틱·인식기·schema) 개선**으로 같은 패턴이
  다시 안 들어오게 하는 게 1순위, 손-config/손어댑터는 그게 불가능할 때만.
  이 프로젝트 (`poisonous60/notice-watcher` 의 dev박스 clone) 전용.
---

이 프로젝트는 게시판 글을 선언적 config(JSON)로 수집한다. `register.py` 가 probe 후 경량 LLM 으로 config 를
자동 생성하고, 실패하면 `output/poll_state/<slug>.FAILED.json` (register.py: `reason`/`last_feedback`/`last_config`)
+ `output/triage_queue.jsonl` (봇: `ts`/`url`/`slug`/`via`/`requested_by`/`register_tail`) 두 곳에 흔적.
이 스킬은 그 흔적을 dev박스로 가져와 진단·해결하고 N100 으로 배포한다. **추측하지 말고 아래 순서대로, 각 단계
산출물을 실제로 확인하며 진행한다.**

## 먼저 펼쳐 볼 것 (전부 읽지 말고 해당 단계에서 필요한 만큼)
- `engine/config_schema.py` 상단 docstring — config 스키마의 정확한 정의(최우선 근거).
- `docs/config 기반 엔진 가이드.md` — 전략(httpx_html/httpx_json/playwright_html/handwritten)·실행·폴링.
- `docs/config 자동생성 실패 케이스.md` — `[FAIL] <체크>` 별 원인·대응 분류. **진단의 기준**.
- `docs/사이트 어댑터 추가 가이드.md` — config 로 표현 안 될 때 손어댑터 추가 표준 절차.
- `docs/운영 메모.md` §1~3, §8 — N100 SSH/IP/venv/systemctl, 워크플로(이 dev 폴더가 곧 `notice-watcher` repo 의 clone — 직접 `git commit && git push` → N100 `git pull`).
- `docs/사이트별 등록 시도 기록.md` — 사이트별 시도/해결 로그. **끝나면 항목 추가/갱신(상태 이모지: ✅자동 / 🔧손config / 🧩손어댑터 / 🛑휴리스틱-거부 / ❌FAILED / 🚫거부)**.
- 레퍼런스 config(`configs/*.json`): httpx_html=`skku_cse_1582`·`mabinogimobile.nexon.com_News_notice`, httpx_json=`endfield_official`·`forum.nexon.com_bluearchive_board_list_board_1018`·`game.naver.com_lounge_Trickcal_board_3`, handwritten=`arca_akendfield`·`cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L`·`m.cafe.daum.net_umamusume-kor_Z4os_boardType`.
- 현재 손어댑터 목록: `adapters/__init__.py` (navercafe=`NaverCafeAdapter`, daumcafe=`DaumCafeAdapter`, arca=`ArcaLiveAdapter`, dcinside=`DCInsideMGalleryAdapter`, skku=`SkkuCseAdapter`, endfield=`EndfieldAdapter`).
- **`engine/recognizers/`** (패키지 — 과거 단일 파일 `engine/known_platforms.py` 에서 분리됨, commit `86437a2`) — 알려진 플랫폼 URL 인식기. register.py 가 probe 전에 `recognize(url)` 를 먼저 본다 — URL 이 매칭되면 그 자리에서 config 만들어 등록(probe/Gemini 생략). 각 플랫폼은 `engine/recognizers/<plat>.py` *한 파일* — `NAME`, `PATTERNS=[(re.Pattern, builder), ...]` export. auto-discovery 가 모든 모듈을 자동으로 잡음. 현재 인식: 네이버 카페(`naver_cafe.py`)·다음 카페(`daum_cafe.py`)·아카라이브(`arca_live.py`)·디시 미니갤(`dcinside_mgallery.py`)·넥슨 포럼(`nexon_forum.py`)·네이버 게임 라운지(`naver_game_lounge.py`)·Reddit(`reddit.py`).

---

## 0. 진입 — 사용자가 어떻게 들어오나

대부분 봇(N100)에서 사용자가 `/preview`·`/watch` 했는데 자동 등록 실패해 triage 큐에 들어온 사이트들을 처리하는
케이스. 사용자가 "FAILED 처리", "triage", "이 사이트 등록" 같은 말로 부른다.

드물게 사용자가 *링크 하나*만 들고 오는 경우(아직 봇으로 시도 안 한 새 사이트):
- `python -c "from engine.recognizers import recognize; import json; print(json.dumps(recognize('<URL>'), ensure_ascii=False, indent=1))"` 로 인식기 매칭 확인.
- 매칭되면 `python scripts/register.py "<URL>"` → 끝(↓ §5 배포만).
- 매칭 안 되면 `python scripts/register.py "<URL>"` 한 번 돌려보고 — 성공하면 끝, 실패하면 그 자리에서 `.FAILED.json` 생기니까 ↓ §1 부터 같은 흐름.

## 1. 가져오기 + 진단

```
python scripts/triage.py pull          # N100 → 로컬 (FAILED.json + triage_queue.jsonl + 실패 slug 의 probe/)
python scripts/triage.py list          # 받아온 실패 목록 표
python scripts/triage.py show <slug>   # 그 slug 의 .FAILED.json(reason/last_feedback/last_config) + 요청자 + probe 산출물 목록
```

IP 바뀌었으면 `DEPLOY_HOST=aaaa@<새IP>` 환경변수.

`show` 출력의 `last_feedback`(=`[FAIL] <체크>`), `last_config`(자동 생성된 마지막 시도 — selector/path 한두 개만 고치면 될 때도 많음), `output/probe/<slug>/` 의 `summary.txt`·`list_candidates.json`·`article_candidates.json`·`traffic.har`·`diagnosis.json` 을 본다. `docs/config 자동생성 실패 케이스.md` 의 §번호에 매칭해 원인 분류.

**진단 직후 — 두 트랙 동시 검토 (필수)**. 두 트랙 모두 *각 케이스마다* 진행 — 한쪽이 다른 쪽 막는 게이트 X.

- **트랙 A (사용자 향 — 사이트 즉시 작동)**: 사용자가 등록 요청한 사이트가 *지금 안 됨* → 작동시켜야 함. 2a~2d 중 매칭 있으면 그게 곧 트랙 A 해결 수단; 없으면 2e (손-config / 손어댑터) 로 작동시킴. 트랙 A 는 *항상* 결과물 있음 (사이트 작동 또는 거부 마커).

- **트랙 B (미래 향 — 같은 패턴 자동 처리)**: 진단 중 *probe 일반화 가능성* 별개로 검토. 손-config 으로 트랙 A 끝낸 케이스도 트랙 B 검토는 의무. 후보:
  - 2a: URL 이 알려진 플랫폼 가족이거나 인식기 PATTERNS 한 줄 추가로 풀리나? (확인: `recognize('<URL>')`)
  - 2b: probe `first_article_url` 이 사이드바/pagination 잘못 잡혔나? 진짜 글 URL 손에 있으면 `--article-url` 로 재시도 가능.
  - 2c: probe artifact 에 *이미 있는 신호*인데 휴리스틱화 안 돼서 LLM 이 4회 retry 한 거 아닌가? (예: row url 외부 도메인 다수 / login redirect / SPA shell / pagination meta 등) → 휴리스틱 신규 또는 retry feedback hint 추가로 미래 같은 패턴 자동 처리.
  - 2d: probe 자체가 잘못 동작 (글 페이지 render 가 sibling page 열음 / HAR 비어있음 / list_candidates 가 명백한 row 못 잡음) → probe/ 수정 + 재-probe.

각 후보 한 줄 점검 (`X — 매칭 X 이유: …` 또는 `O — <적용 자리>`). 매칭 있으면 *같은 PR* 에 트랙 A 와 함께 박는다. 매칭 0건이면 case 파일 본문 또는 `_note` 에 한 줄 이유 명시 ("이 사이트만의 storage_state 필요" / "신호는 휴리스틱화 가능하나 활용처 없음" 등). 미래 2개째 비슷한 사이트 들어왔을 때 즉시 알아채는 비용 절감.

예시: `host_scholar-google-_scholar_706d9c49` (commit `0b130b2`) — 트랙 A 손-config `configs/host_scholar-google-_scholar_706d9c49.json` + 트랙 B (C) `probe/extract.py:list_row_external_host` + (D) `generate/validate.py:_external_host_hint`. 동시.

## 2. 분기 — 위에서부터 차례로 따져 첫 매칭

**핵심 원칙**: 같은 패턴이 미래에 또 큐에 쌓이지 않게, *자동 파이프라인 자체*를 개선하는 분기(2a~2d) 가
손-config(2e) 보다 우선. 같은 사이트 하나만 고치고 끝나면 미래 비슷한 케이스가 또 4회 retry + triage 큐 진입을 반복한다.

### 2a. 이미 알려진 플랫폼 / 또는 인식기만 넓히면 됨

`python -c "from engine.recognizers import recognize; print(recognize('<URL>'))"`.
- 매칭되면 → 그냥 `python scripts/register.py "<URL>"` (이 실패는 인식기 추가되기 전 거였거나 봇이 옛 코드일 때 난 것).
- 매칭은 안 되지만 같은 플랫폼의 다른 게시판이 이미 손어댑터/손config 로 있으면(예: 다음카페 다른 게시판인데 인식기가 그 URL 형태를 아직 안 받음) → `engine/recognizers/<해당-플랫폼>.py` 의 `PATTERNS` 에 그 URL 형태를 받는 패턴 추가/확장 → `register.py "<URL>"`. (그 플랫폼 전체가 자동으로 풀린다.)

### 2b. probe 가 '첫 글'을 잘못 집음 — `--article-url` 재시도

`list_candidates.json` 의 `first_article_url` 이 사이드바/메뉴 링크일 때. 보통 `[FAIL] posts_nonempty` 나 `[FAIL] article_body_len` + `[warn] matches_probe_first_article` 동반.

→ 그 게시판의 진짜 글 하나 URL 을 찾아서 `python scripts/register.py "<목록URL>" --article-url "<글URL>"` (probe 산출물 재사용하려면 `--reuse-probe` 도). first_article_url 교정 + 그 글페이지 render+HAR re-probe + 강한 hint 로 처음부터 재생성. 성공하면 손작성 없이 끝 → §5 배포.

### 2c. probe 가 *데이터로 검출 가능한* 한계를 안 잡음 — 휴리스틱 추가 (1순위)

probe 산출물(`diagnosis.json`·`list_candidates.json`·HAR 등) 에 *이미 신호는 있는데* 그걸 휴리스틱화·preflight 거부로 안 연결해서 LLM 이 4회 retry 후 fail 하는 경우. **손 config 보다 우선** — 같은 패턴 미래 사이트도 자동 처리.

**probe 가 현재 추출 중인 신호** — 단일 진실원은 `probe/_contract.py:_ARTIFACTS` 의 각 `_ContractField.note`. 7종 산출물 × 필드별 한 줄 설명. 새 휴리스틱 자리 후보인지 판단할 땐 *거기에 없는 카테고리*인지부터 확인 — 있으면 기존 휴리스틱 보강 자리지 신규 자리가 아님.

휴리스틱화 가치 있는 카테고리는 보통: ① 페이지에 *직접 박힌 fact* (URL · ID · 헤더 · 메타) 인데 현 휴리스틱이 안 추출, ② LLM 이 raw HTML/HAR 만 보고는 *자주 틀리는* 신호 (login gate · paywall · geo block · client-side route · pagination meta · 본문 컨테이너 안정 selector), ③ preflight 거부 가능한 *영구 차단* 신호. 셋 다 아니면 휴리스틱 안 박는 게 낫다 (LLM 이 raw 데이터에서 직접 보게).

처리:
1. `probe/extract.py`(또는 적절한 `probe/` 파일)에 새 `@heuristic` 함수 추가. 입력: 이미 있는 probe artifact (또는 fetch 된 HTML/HAR — *추가 네트워크 fetch 금지*; 휴리스틱은 순수해야). 출력: `diagnosis.json` 또는 `list_candidates.json` 에 명시적 키 (예: `{"login_gate": {"gated": True, "redirect_host": "...", "sample_url": "..."}}` 또는 위 runtime_id_candidates 형태의 후보 list).
2. **그 키를 어떻게 쓸지 *동시에* 박아라**:
   - LLM 이 활용 → `prompts/config_writer.system.txt` 에 그 키 설명 한 줄 추가 + `_PROMPT_REQUIRED_KEY_PATHS` 등록.
   - register.py preflight 가 거부 → 그 키 보면 즉시 fail with `reason="..."`, LLM 호출 skip (4회 retry 비용 0).
   - recognizer 후처리가 활용 → 별도 자리 (recognizer 는 probe 못 봄 → register.py 가 recognize 결과를 probe digest 와 merge 하는 단계 추가 필요. 현재 그 단계 X — 그쪽 자리는 F-layer 변경.).
3. **거부 마커**: 같은 사용자가 또 `/preview`·`/watch` 누르면 또 큐에 쌓이지 않게 하려면 `.REJECTED.json` 마커 + `bot/site_ops.py:is_registered` 가 그것도 보게 — 다만 이건 *봇 코드 변경*이라 별도 PR. 우선 휴리스틱+preflight 만으로도 4회 retry skip 효과는 즉시.
4. **휴리스틱 추가 규칙** (↓ §4) 따라 fixture·contract·smoke 통과.

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

- **새 휴리스틱 함수**: 새 순수(외부 의존 X) 함수는 ① `@heuristic` 데코레이터(`from probe._heuristic import heuristic`) ② `tests/probe_heuristics/test_<함수명>.py` 에 unit fixture (`run() -> list[(case_name, ok, msg)]`) ③ 수정 후 반드시 `python scripts/probe_smoke.py` 통과 확인 (stage 5 가 coverage 검증). 빠뜨리면 다운스트림 silent fail.
- **산출물 파일/키 추가·변경**: 산출물 키는 `engine/digest.py`·`scripts/register.py`·`prompts/config_writer.system.txt` 가 하드코딩으로 읽어 silent fail 의 진원지. 한 곳에서 막는다. ① `probe/_contract.py` 의 `OUTPUT_SCHEMA` 갱신(`ArtifactContract`: 필수/옵션 키, `type_hint`, 필요시 `prompt_aliases`) ② write 측에 `validate_payload("<file>.json", payload, allow_extra=False)` 호출 추가/유지 (`probe/extract.py:write_list_candidates`, `probe/discover.py`, `probe/report.py`, `probe/fetch_headless.py`, `scripts/register.py` 의 article_candidates 분기) ③ 키가 프롬프트에 등장해야 하면 `probe/_contract.py` 의 `_PROMPT_REQUIRED_KEY_PATHS` 에 `(file, key)` 추가하고 `prompts/config_writer.system.txt` 에 그 키(또는 `prompt_aliases` 의 자연어 변형) 워드바운더리로 등장하게 ④ **새 산출물 파일 추가**면 `tests/probe_heuristics/test_contract.py` 의 `output_schema_completeness` 케이스 expected set 에도 그 파일명 추가 ⑤ `python scripts/probe_smoke.py` 통과 확인 — stage 1·1b·1c.

## 5. 검증 + N100 배포 (모든 분기 공통)

1. `python scripts/probe_smoke.py` 그린.
2. 자가 점검 7-질문 (↓ §6) — 비워도 commit 막진 X, 그저 생각해두는 게이트.
3. `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py`.
4. (권장) `hand-config-reviewer` subagent 호출 (↓ §7). PASS 받으면.
5. `docs/사이트별 등록 시도 기록.md` 갱신 (상태 이모지·원인·해결).
6. **commit + push**:
   - 바뀐 파일들 stage (`configs/<slug>.json` + 인식기/휴리스틱/엔진/스크립트/docs).
   - `git add <...>; git commit -m "<요지>"; git push origin main` — commit msg 끝에 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. pre-push hook 이 probe_smoke 자동 실행 → FAIL 이면 push 차단(`--no-verify` 금지).
   - **단일 commit 정책 권장** — 한 skill 실행 = 한 commit (track A + B 한 묶음). `case_log` 의 `files_changed` derive 가 `git diff HEAD~1..HEAD` 로 마지막 1 commit 만 보기 때문 — 다중 commit 분리하면 첫 commit 변경 미캡쳐.
6.5. **case_runs DB row** (필수, 코드 변경 X 도 — `docs/case_runs DB 계획.md`):
   ```bash
   python scripts/case_log.py log \
     --slug <slug> --skill hand-config \
     --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \
     --reason "<1-3줄 — 무엇 시도, 왜 그 결과>" \
     [--fix-layer <C+D>] [--failure-keys <key1,key2>] [--case-md-slug <slug>]
   ```
   outcome 분류:
   - `improved` — fix_layer 기반 코드 일반화 (휴리스틱·prompt 룰 추가·인식기·엔진) + 효과
   - `handcrafted` — 손-config 또는 신규 손어댑터로 *그 사이트만* 작동 (코드 일반화 X)
   - `no_change` — 시도했으나 효과 X (revert 또는 동등 출력)
   - `rejected` — 정책 거부 마커
   - `rejected_with_policy` — no-change 인데 영구 기록 가치 정책 결정
   - `error` — skill 도중 미완 (정상 흐름엔 박지 X — 사람 사후 박기)

   잊어도 push 차단 X (~10% gap 수용). dashboard `/cases` 에서 표시.
7. **N100 pull + register + (필요시) restart** (`docs/운영 메모.md` §8):
   - `ssh aaaa@<lan-ip> 'cd ~/notice-watcher && git pull --ff-only && .venv/bin/python scripts/register.py --config "configs/<slug>.json"'` ← **반드시 `.venv/bin/python`**(시스템 python 엔 httpx 없음).
   - `requirements.txt` 변경 시 앞에 `.venv/bin/pip install -r requirements.txt &&`.
   - **`adapters/`(`__init__.py` 포함) 또는 `engine/`·`scripts/notify.py`·`bot/` 수정 시 반드시 뒤에 `&& systemctl --user restart notice-bot.service`** — 봇은 장기 실행 프로세스라 import 캐시. 새 어댑터 파일만 pull 하고 봇 재시작 안 하면 `make_adapter()` → `ValueError("handwritten adapter 클래스 없음")` → `/preview` 가 "예시를 만들지 못했어요…" 만 뱉음. 순서: **pull → (필요시 pip install) → register --config → restart**.
   - 확인: `ssh aaaa@<lan-ip> 'cd ~/notice-watcher && .venv/bin/python scripts/register.py --list'` 에 그 slug 가 `registered` 로.
   - N100 IP 는 DHCP — `ssh` 안 되면 콘솔에서 `ip a` (운영 메모 §1~2).
8. 처리 끝나면 `.FAILED.json`·`triage_queue.jsonl` 의 그 slug 항목은 `register.py --config` 가 자동 정리(2e 의 경우). 2a/2b 의 경우는 `register.py "<URL>"` 가 정리. 2c/2d 의 경우(휴리스틱·probe 수정 후 재-register) 도 동일.
9. (선택) 요청자에 알림 — 봇에 그런 명령은 없으니 owner DM 으로 알리거나 사용자에게 다시 `/watch` 권유. 2c 의 *영구 거부* 케이스면 "비공개 사이트라 등록 불가, storage_state 로그인 경로 필요" 안내.

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

2. **이전 케이스 있나?** — `Grep '<failure_key 또는 root_cause>' docs/cases/` 또는 `Read docs/cases/INDEX.md`. 있으면 그때 어느 자리에 박았나 — 일관 유지. 다른 자리에 박을 거면 이유 명시.

3. **누구 깰까?** — 21+ configs 중 영향 사이트 enumerate. 0개 가능하지만 *왜 0개인지* 한 줄 적기.

4. **검증 그린?** —
   - `python scripts/probe_smoke.py` 그린
   - 영향 사이트 있으면: `python scripts/register.py --config "configs/<영향-slug>.json"` 결과 비교
   - LLM 거동 영향 (C/A/B) 이면: 가장 최근 실패 케이스의 probe artifact 로 `register.py --reuse-probe` 1회 — 산출 config 동등 또는 더 좋은지.

5. **case 파일 + commit msg** — 
   - `docs/cases/<slug>.md` 작성. frontmatter:
     - 필수: `slug`, `url`, `status` (이모지 + 1줄 narrative), `outcome` (DB 캐노니컬 — `improved|handcrafted|no_change|rejected|rejected_with_policy|error`), `date`
     - 선택: `fix_layer`, `failure_keys`, `config_strategy`, `adapters_changed`, `engine_files_touched`, `tags`, `requested_by`
   - `outcome` 분류 (§5.10 의 case_log 호출 outcome 과 동일):
     - `improved` — fix_layer 기반 코드 일반화 (휴리스틱·prompt 룰·인식기·엔진) + 효과
     - `handcrafted` — 손-config / 신규 손어댑터로 그 사이트만 작동 (fix_layer 키 X)
     - `rejected` — 정책 거부 마커
     - `rejected_with_policy` — no-change 인데 영구 기록 가치 정책 결정
     - `no_change` — 시도했으나 효과 X (case .md 보통 X — narrative 가치 있을 때만)
   - `python scripts/cases_index.py --backfill-db output/cases.sqlite3` 실행해 INDEX.md 갱신 + DB row sync.
   - commit msg prefix 권장: `[fix-layer: E|D|C|B|A|F|none] <slug>` + 본문에 자가 점검 답 요약 (특히 §6 의 1번 fix-layer 매핑, 7번 일반화 시도/포기 사유).

6. **새 패턴이면 smoke_test fixture 추가했나?** — 다음 둘 중 하나에 해당하면 fixture 동시 추가 의무:
   - **새 strategy 도입 (F-layer)**: `engine/strategies/<new>.py` 신규 추가 시 → `scripts/probe_smoke.py` 의 `REPS` 에 그 패턴을 *진짜로 보여주는* 새 entry 추가 + 그 URL probe → `output/probe/<new-slug>/` 산출 + `_stage2_check_digest` 안에 slug-specific 검증 분기 추가.
     ※ fixture URL 선택 주의 — *진짜로 그 패턴을 보여주는* URL 인지 직접 probe 결과로 확인. (이 SKILL 의 §6 6번 질문 추가 trigger = 2026-05-15 `probe_smoke.py` 의 REPS fixture URL `endfield.gryphline.com/ko-kr/news` 잘못 박힘 사례 — Next.js prerender 라 클라이언트 XHR 안 함 → SPA+XHR 패턴 fixture 로 부적절. adapter 자체는 별도 도메인 `web-news.gryphline.com/api/bulletin` 직접 hit 라 정상.)
   - **새 휴리스틱 도입 (C-layer)**: `probe/extract.py` 또는 `probe/_heuristic.py` 에 새 `@heuristic(...)` 함수 추가 시 → `tests/probe_heuristics/test_<heuristic_name>.py` 동시 추가. stage 5 가 자동 picked-up 인데 fixture 없으면 의미 없음.

   기존 strategy/heuristic 수정만이면 skip.

7. **트랙 A + 트랙 B 둘 다 진행했나?** — 트랙 A (사용자 향, 사이트 즉시 작동 — 손-config / 손어댑터 / 인식기 확장 / probe 수정 / 거부 마커 중 하나) 는 *항상* 결과물 있어야 함 (사용자 사이트 안 돌게 두는 건 SKILL 실패). 트랙 B (미래 향, probe 일반화 — 2a~2d 후보 검토) 는 *케이스마다 검토 의무*, 매칭 있으면 같은 PR 에 박음.
   - 둘 다 했으면 fix_layer 에 두 자리 표기 (예: `C+D` = probe 휴리스틱 + retry feedback + 별도 손-config 함께. 손-config 자체는 fix_layer 키 X — case file status 에 🔧 으로 표시).
   - 트랙 B 매칭 0이면 `_note` 또는 case body 에 "일반화 안 되는 이유: <코너 케이스 한 줄>" 명시. (예: "이 사이트만의 storage_state 필요" / "신호는 휴리스틱화 가능하나 활용처 없음 — 미래 2번째 케이스 들어오면 박을 자리만 메모")
   - 미래 같은 패턴 사이트 2개째 들어오면 *그때* 트랙 B 실제 코드 박아도 늦지 X. 다만 1개째에 *후보 자리 기록* 안 남기면 못 알아챔 — case file 이 기록 매개체.

위 일곱 답이 없어도 commit 막지 X — 그저 *생각해보면 좋은* 질문. 진짜 검증은 reviewer subagent + pre-push hook.

## 7. 자가 review (commit 직전 — 권장)

코드 변경(휴리스틱·인식기·엔진·schema·prompt) 또는 손-config 변경 (1+ 파일) 을 commit 하기 직전에 `hand-config-reviewer` subagent 호출. **순서: §5 step 6.5 의 case_log 호출 → 그 결과 query → reviewer prompt 에 박음**:

```
# main thread (Claude Code) — reviewer 호출 *전*:
case_row_json = Bash('python scripts/case_log.py query --slug <slug> --recent 1 --format json')
# 결과 = '[]' (log 호출 잊음) 또는 '[{...}]' (정상)

Agent(
  subagent_type='hand-config-reviewer',
  model='sonnet',
  prompt='''
    ## 변경 diff
    [git diff HEAD 결과]

    ## case 파일
    [docs/cases/<slug>.md 의 frontmatter + body]

    ## probe_smoke 결과
    [python scripts/probe_smoke.py 의 stdout + exit code]

    ## case_runs row (이번 실행 — 최근 1일)
    {case_row_json}

    ## (선택) 영향 사이트 손-실행
    [register.py --config 출력 비교]

    위 변경을 검증 항목에 비추어 PASS/FAIL. 추가:
    - case_runs row 가 `[]` 면 main thread 가 case_log 호출 잊음. PASS 가능 but warn 표시.
    - row 의 fix_layer / files_changed / failure_keys 가 case .md frontmatter 와 일치하나? 모순이면 FAIL.
    - row 의 outcome 이 case .md status 와 일치하나? (🔧 → handcrafted, ✅ → improved 등)
  '''
)
```

reviewer 는 Bash 없음 — main thread 가 `probe_smoke`·`case_log query` 등 실행 후 결과를 prompt 에 박아 넘긴다. reviewer 는 *판단만*.

FAIL 받으면 → **사용자에게 보고**. 자동 재호출 X (비결정 위험 회피). 사용자가 픽스 결정.
