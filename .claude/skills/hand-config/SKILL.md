---
name: hand-config
description: >-
  게시판/공지 URL 로 손작성 config(또는 손어댑터)를 만들어 등록·N100 배포하는 워크플로우.
  사용자가 링크를 주며 "손 config 작성", "이 사이트 등록해줘", "config 만들어줘" 라고 할 때(모드 A),
  또는 봇 /preview·/watch 자동 등록이 실패한 사이트들을 모아 처리(triage)하라고 할 때(모드 B) 사용.
  이 프로젝트 (`poisonous60/notice-watcher` 의 dev박스 clone) 전용.
---

이 프로젝트는 게시판 글을 선언적 config(JSON)로 수집한다. 경량 LLM 자동 생성(`register.py "<URL>"`)이
실패하는 사이트는 사람이 손으로 config(또는 `adapters/` 손어댑터)를 만들어 `register.py --config` 로 등록한다.
이 스킬은 그 절차 + N100 배포 + triage 큐 처리를 안다. **추측하지 말고 아래 순서대로, 각 단계 산출물을 실제로 확인하며 진행한다.**

## 먼저 펼쳐 볼 것 (전부 읽지 말고 해당 단계에서 필요한 만큼)
- `engine/config_schema.py` 상단 docstring — config 스키마의 정확한 정의(최우선 근거).
- `docs/config 기반 엔진 가이드.md` — 전략(httpx_html/httpx_json/playwright_html/handwritten)·실행·폴링.
- `docs/config 자동생성 실패 케이스.md` — `[FAIL] <체크>` 별 원인·대응 분류. **triage(모드 B) 진단의 기준**.
- `docs/사이트 어댑터 추가 가이드.md` — config 로 표현 안 될 때 손어댑터 추가 표준 절차.
- `docs/운영 메모.md` §1~3, §8 — N100 SSH/IP/venv/systemctl, 새 워크플로(이 dev 폴더가 곧 `notice-watcher` repo 의 clone — 직접 `git commit && git push` → N100 `git pull`).
- `docs/사이트별 등록 시도 기록.md` — 사이트별 시도/해결 로그. **끝나면 항목 추가/갱신(상태 이모지: ✅자동 / 🔧손config / 🧩손어댑터 / ❌FAILED / 🚫거부)**.
- 레퍼런스 config(`configs/*.json`): httpx_html=`skku_cse_1582`·`mabinogimobile.nexon.com_News_notice`, httpx_json=`endfield_official`·`forum.nexon.com_bluearchive_board_list_board_1018`·`game.naver.com_lounge_Trickcal_board_3`, handwritten=`arca_akendfield`·`cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L`·`m.cafe.daum.net_umamusume-kor_Z4os_boardType`.
- 현재 손어댑터 목록: `adapters/__init__.py` (navercafe=`NaverCafeAdapter`, daumcafe=`DaumCafeAdapter`, arca=`ArcaLiveAdapter`, dcinside=`DCInsideMGalleryAdapter`, skku=`SkkuCseAdapter`, endfield=`EndfieldAdapter`).
- **`engine/known_platforms.py`** — 알려진 플랫폼 URL 인식기 목록. register.py 가 probe 전에 여기를 먼저 본다 — URL 이 매칭되면 그 자리에서 config 만들어 등록(probe/Gemini 생략). **플랫폼 단위 작업을 끝냈으면 여기에 인식기 한 줄 추가**(↓ 모드 A 8b / 모드 B). 현재 인식: 네이버 카페·다음 카페·아카라이브·디시 미니갤·넥슨 포럼·네이버 게임 라운지.

---

## 모드 A — 링크 하나 → 손 config 작성 → 등록 → N100 배포

0. **이미 알려진 플랫폼인가?** — `python -c "from engine.known_platforms import recognize; import json; print(json.dumps(recognize('<URL>'), ensure_ascii=False, indent=1))"`.
   - **매칭되면** 손작업 필요 없음 → 그냥 `python scripts/register.py "<URL>"` (probe/Gemini 없이 즉시 등록) → 모드 A 8~10(doc·N100 배포)만. 끝.
   - 매칭은 안 되는데 **같은 플랫폼의 다른 게시판이 이미 손어댑터/손config 로 있으면**(예: 다음카페 다른 게시판인데 인식기가 그 URL 형태를 아직 안 받음) → `engine/known_platforms.py` 의 `_RECOGNIZERS` 에 그 URL 형태를 받는 인식기를 추가/확장하는 게 1순위(그러면 그 플랫폼 전체가 자동). 그게 아닌 진짜 새 사이트면 ↓ 1번부터.
1. **slug 확정** — `python -c "from probe.paths import url_to_slug; print(url_to_slug('<URL>'))"`. config 파일명·state 파일명·doc 항목 모두 이 slug.
2. **probe** — `python scripts/probe.py "<URL>"` (느리면 `--lite`). `output/probe/<slug>/` 의 `summary.txt`·`list_candidates.json`·`article_candidates.json`·`traffic.har`·`diagnosis.json` 확인.
   - 봇이 이미 자동 등록을 시도했었다면 `output/poll_state/<slug>.FAILED.json` 의 `last_feedback`(=`[FAIL] <체크>`)·`last_config` 부터 본다 — 뭐가 막혔는지·LLM 이 어디까지 갔는지 거기 다 있다. 로컬에 없으면 모드 B의 `triage.py pull` 로 N100 에서 가져온다.
3. **전략 선택**
   - **이미 그 사이트 손어댑터가 `adapters/` 에 있으면** → 가장 간단. `strategy:"handwritten"`, `adapter:"<클래스명>"`, `kwargs:{...}` 만. (네이버 카페·아카라이브·디시·SKKU 등이 여기. URL 에서 cafe/menu id, channel slug 등을 뽑아 kwargs 로.)
   - 정적 HTML 목록 + 정적 HTML 본문 → `httpx_html`. probe 의 `list_candidates.json`·HAR 로 `row_selector`·각 field selector 작성.
   - 목록 또는 본문이 JSON XHR → 목록이면 `httpx_json`(+`list_path`), 본문이면 `article.fetch_kind:"json"`(+`data_path`). HAR 에서 그 API URL·응답 트리 확인.
   - JS 렌더인데 `goto`+networkidle 로 잡힘 → `playwright_html` + `wait_selector`.
   - 클릭/스크롤 후에야 뜨거나 Cloudflare 챌린지가 강함 → `docs/사이트 어댑터 추가 가이드.md` 따라 손어댑터를 새로 작성 → 그 다음 handwritten config 로 감쌈.
4. **config 작성** — `configs/<slug>.json`. 필수 키: `version`(1)·`site`·`board`·`strategy`. httpx_*/playwright 면 `list.url_template` + `list.fields.{post_id,title}` 필수. `_source_url` 에 원본 URL(register.py 가 state 의 url 로 씀). 손작성한 이유를 `_note` 에 한 줄. 레퍼런스 config 를 베껴 시작.
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
   목록 0건이거나 본문 0자면 config 가 틀린 것 → 4로 돌아가 고친다.
7. **로컬 등록** — `python scripts/register.py --config "configs/<slug>.json"` → `output/poll_state/<slug>.json` baseline 생성. 같은 slug 의 `.FAILED.json`·`triage_queue.jsonl` 항목은 `_save_state` 가 자동 정리.
8. **doc 갱신** — `docs/사이트별 등록 시도 기록.md` 에 항목 추가/갱신: 상태 이모지, (자동) 실패 원인, 무엇을 어떻게 했나(어떤 strategy/adapter, 어떤 selector/kwargs).
   - **이게 *플랫폼*이면**(특정 사이트 하나가 아니라 같은 패턴 게시판이 여럿 — 네이버/다음 카페, 넥슨 포럼류) → `engine/known_platforms.py` 의 `_RECOGNIZERS` 에 URL 인식기 한 줄 추가(builder 가 이번에 만든 config 와 동형의 dict 를 돌려주게). 그러면 같은 플랫폼의 다음 게시판은 `/watch`·`/preview` 만으로 즉시 등록됨. `python -c "from engine.known_platforms import recognize; print(recognize('<다른 게시판 URL>'))"` 로 확인. 잘못 매칭해도 fetch_list 0건이면 폴백하니 안전.
9. **N100 배포** (`docs/운영 메모.md` §8) —
   - dev 폴더 자체가 `notice-watcher` repo dev clone 이라 별도 cp 단계 없음. 바뀐 파일들(`configs/<slug>.json` + 손어댑터면 `adapters/<x>.py`·`adapters/__init__.py` + 인식기면 `engine/known_platforms.py` + 엔진/스크립트면 그것 + `docs/사이트별 등록 시도 기록.md`)을 그대로 stage.
   - `git add -A; git commit -m "<요지>"; git push origin main`  (커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`)
   - `ssh aaaa@<lan-ip> 'cd ~/notice-watcher && git pull --ff-only && .venv/bin/python scripts/register.py --config "configs/<slug>.json"'`  ← **반드시 `.venv/bin/python`**(시스템 python 엔 httpx 없음). 손어댑터/엔진에 새 import 추가했으면 앞에 `.venv/bin/pip install -r requirements.txt &&`.
   - **`adapters/` 에 파일을 새로 추가/수정했거나(`__init__.py` 포함), `engine/`·`scripts/notify.py`·`bot/` 을 고쳤으면 반드시 뒤에 `&& systemctl --user restart notice-bot.service`** — 봇은 장기 실행 프로세스라 켜져 있는 동안 import 된 모듈이 캐시됨. 새 어댑터 파일만 pull 하고 봇을 재시작 안 하면 `make_adapter()` 가 `getattr(adapters, "<클래스명>")` → None → `ValueError("handwritten adapter 클래스 없음")` → `/preview` 가 "예시를 만들지 못했어요(목록이 비었거나 본문 추출 실패)" 만 뱉는다(실제 원인은 어댑터 클래스 못 찾음). 또 `git pull` 과 `register.py --config` 사이/직후에 봇을 재시작하면 새 모듈을 못 받으니, **순서는 pull → (필요시 pip install) → register --config → restart** 로.
   - 확인: `ssh aaaa@<lan-ip> 'cd ~/notice-watcher && .venv/bin/python scripts/register.py --list'` 에 그 slug 가 `registered` 로.
   - N100 IP 는 DHCP — `ssh` 가 안 되면 콘솔에서 `ip a` (운영 메모 §1~2).
10. 사용자에게: 봇에서 `/preview <URL>` 또는 `/watch <URL>` 하면 된다고 알린다.

---

## 모드 B — 실패한 /preview·/watch 일괄 처리 (triage)

봇(N100)에서 사용자가 `/preview`·`/watch` 했는데 자동 등록이 실패하면 두 곳에 남는다:
`output/poll_state/<slug>.FAILED.json`(register.py: `reason`/`last_feedback`/`last_config`) + `output/triage_queue.jsonl`(봇: `ts`/`url`/`slug`/`via`/`requested_by`/`register_tail`). 이걸 dev박스로 가져와 하나씩 해결한다.

1. **가져오기** — `python scripts/triage.py pull` (N100 의 `*.FAILED.json` + `triage_queue.jsonl` + 각 실패 slug 의 `output/probe/<slug>/` 를 로컬로). IP 바뀌었으면 `DEPLOY_HOST=aaaa@<새IP>` 환경변수.
2. **목록** — `python scripts/triage.py list` → slug · 실패시각 · via · 요청자 · `[FAIL] <체크>` · URL.
3. **하나 골라 진단** — `python scripts/triage.py show <slug>` → `.FAILED.json` 전문(reason/last_feedback/**last_config**) + 요청자 + `output/probe/<slug>/` 목록. `docs/config 자동생성 실패 케이스.md` 의 §번호에 매칭해 원인 분류:
   - **이미 알려진 플랫폼 / 또는 인식기만 넓히면 되는 경우** — `python -c "from engine.known_platforms import recognize; print(recognize('<URL>'))"`. 매칭되면 그냥 `register.py "<URL>"` 로 끝(이 실패는 인식기가 추가되기 전 거였거나, 봇이 옛 코드일 때 난 것). 매칭은 안 되지만 같은 플랫폼의 다른 게시판이 이미 처리돼 있으면 → `engine/known_platforms.py` 인식기를 그 URL 형태까지 받게 확장 → `register.py "<URL>"`. (그 플랫폼 전체가 자동으로 풀린다.)
   - **probe 가 "첫 글"을 잘못 집음** (`list_candidates.json` 의 `first_article_url` 이 사이드바/메뉴 링크. 보통 `[FAIL] posts_nonempty` 나 `[FAIL] article_body_len` + `[warn] matches_probe_first_article` 동반) → **먼저 `--article-url` 자동 재시도를 시도**: 그 게시판의 진짜 글 하나 URL 을 찾아서 `python scripts/register.py "<목록URL>" --article-url "<글URL>"` (probe 산출물 재사용하고 싶으면 `--reuse-probe` 도). first_article_url 교정 + 그 글페이지 render+HAR re-probe + 강한 hint 로 처음부터 재생성한다. 성공하면 손작성 없이 끝 — `docs/사이트별 등록 시도 기록.md` 갱신하고 N100 배포(모드 A 9~10). 실패하면 ↓.
   - **probe 가 부족/오작동** (글페이지 render 가 잘못된 페이지를 열었다, HAR 가 비었다 등) → `probe/`·`scripts/probe.py` 를 고칠 수 있나 본다. 고치면 재-probe 후 자동 생성 재시도(`python scripts/register.py "<URL>" --reuse-probe` 또는 그냥 `"<URL>"`). 안 되면 ↓.
   - **자동 파이프라인 한계** (JS/iframe 목록, Cloudflare, 비공개판 로그인 필요, 본문이 클라이언트 라우트 등) → **모드 A 의 3~10단계**로 손 config 또는 손어댑터 작성. `last_config` 에서 selector/path 한두 개만 바꾸면 되는 경우도 많다.
4. 처리 끝나면 (모드 A 9단계에서 N100 에서 `register.py --config` 실행하면) 그 slug 의 `.FAILED.json` 과 `triage_queue.jsonl` 항목은 자동으로 사라진다. 큐가 빌 때까지 2~4 반복.
5. (선택) 요청자에게 "올린 사이트 이제 됨" 알림 — 봇에 그런 명령은 없으니, owner DM 으로 알리거나 사용자에게 다시 `/watch` 권유.

---

## 주의
- 한 번이라도 자동 등록을 시도한 slug 는 `.FAILED.json` 이 남아 봇 `_is_registered` 가 False → `/preview` 가 또 자동경로로 돈다. 등록은 반드시 `register.py --config`(또는 자동 성공)로 — 그게 `_save_state` 로 마커를 지운다. config 파일만 `configs/` 에 둬선 봇이 모른다.
- 크롤링 정책(`docs/크롤링 지침.md` §6): `polite_sleep` 은 하한만 올림, robots 존중. 로그인 우회·차단 회피 금지 — 어댑터가 401/403 이면 본문을 비워 반환한다(우회용 코드 넣지 말 것).
- 비공개·등급제한 게시판은 본문 API 가 401/403 → 본문 없이 등록은 되지만 알림에 본문이 빈다. 필요하면 `output/state/<slug>.json`(storage_state) 로그인 경로를 안내.
- 새 손어댑터를 추가했으면 ① `adapters/__init__.py` 의 `import` + `__all__` 에 등록해야 `make_adapter` 가 찾고, ② N100 배포 후 **`notice-bot.service` 를 재시작**해야 켜져 있던 봇이 새 클래스를 본다(↑ 모드 A 9단계). 재시작 안 하면 `/preview` 가 "예시를 만들지 못했어요…" 만 나온다.
