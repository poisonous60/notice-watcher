# config 자동 생성 실패 케이스와 대응

`register.py` (URL → probe → digest → Gemini → config + 검증, 실패 시 escalate)가 **자동으로 config 를 못 만드는** 경우들 정리.
새 사이트를 `/watch` 했는데 안 됐거나 `output/poll_state/<slug>.FAILED.json` 이 생겼을 때, *어떤 종류의 실패인지 알아보고 → 무엇을 해야 하는지* 찾는 용도.

관련 문서: **각 사이트별로 실제 실패했던 원인·해결 기록** = `사이트별 등록 시도 기록.md` (이 문서는 *분류*, 그건 *사례 로그*) / 코드 구조·검증 3층위 = `config 기반 엔진 가이드.md` / 손어댑터 작성 = `사이트 어댑터 추가 가이드.md` / 차단 우회 = `차단 우회 기술 조사 (TLS fingerprint, DPI).md` / 배포·운영 = `운영 메모.md`.

---

## 0. 어디서 실패 정보를 보나

> 봇에서 사용자가 `/preview`·`/watch` 했다 실패한 건들을 **한 번에 모아 처리**하려면: dev박스에서 `python scripts/triage.py pull` (N100 의 `*.FAILED.json` + `output/triage_queue.jsonl` + 각 실패 slug 의 probe 산출물을 가져옴) → `triage.py list` → `triage.py show <slug>` → `hand-config` 스킬 절차로 사이트별 처리(probe 수정 or 손 config/손어댑터 → `register.py --config` → N100 배포). 등록되면 그 흔적은 `register.py` 의 `_save_state` 가 자동 정리.

- **`output/poll_state/<slug>.FAILED.json`** — 자동 등록 실패 마커. `{slug, url, failed_at, reason, last_config, last_feedback}`. `last_feedback` 에 *마지막 검증 결과*(어떤 체크가 FAIL 했나 + 실제 추출된 글들 + 본문 길이)가 들어있음 — **여기를 먼저 봐라**.
- **`output/triage_queue.jsonl`** — 봇이 `/preview`·`/watch` 자동 등록 실패 때마다 append: `{ts, url, slug, via, requested_by, register_tail}` — *누가 어떤 명령으로* 실패시켰는지(요청자에게 다시 알릴 때 쓸 맥락).
- **봇 로그** (`/watch`·`/preview` 로 등록 시도한 경우): `journalctl --user-unit notice-bot.service -f | grep --line-buffered '\[register\]'` — probe 단계·gemini 시도별 PASS/FAIL·escalation 진행이 다 흐름.
- **`register.py --list`** — 등록 현황(`status` 컬럼에 `FAILED` 면 그 사이트).
- **probe 산출물** `output/probe/<slug>/` — `diagnosis.json`(verdict), `list_candidates.json`(row 후보·JSON API 후보·first_article_url), `list.html`/`article.html`(정제 전 HTML), `traffic*.har`(네트워크), `article_candidates.json`(escalation 의 글 본문 API 후보).

---

## 1. 등록 거부 (config 를 아예 안 만듦) — `register.py` 종료코드 2

`_policy_check` 가 막은 것. `.FAILED.json` 안 생기고 그냥 "등록 거부" 로그.

| 증상 | 원인 | 대응 |
|---|---|---|
| `로그인 필요 사이트 (verdict='LOGIN_REQUIRED ...')` | 목록·글이 로그인 뒤에 있음 (네이버카페 비공개판 등) | 자동 미지원. 사람이 한 번 헤드풀로 로그인 → `playwright_html` config 에 `storage_state_path` 로 세션 재사용 (손작성). 세션 만료 시 재로그인 필요. |
| `목록 페이지에 정적으로도 headless 로도 접근 실패 ... 차단(BLOCKED) 사이트로 보임` | `BLOCKED_BOT`(UA/헤더 필터) / `BLOCKED_IP` / `BLOCKED_GEO` — 정적 GET 도 chromium 도 빈 페이지/차단 페이지를 받음 | 차단 우회는 자동 경로에서 안 함. (a) N100 은 한국 주거지 IP라 KR 사이트엔 유리 — 그래도 막히면 (b) 프록시/유료 스크래핑 API(ScraperAPI 무료 등) 검토 — `차단 우회 기술 조사 ...md`, (c) Cloudflare 챌린지면 `handwritten`+playwright-stealth (§4). robots `Disallow` 만이면 *거부 아님* — 경고만 띄우고 진행함. |

---

## 2. config 생성 실패 → escalate 후에도 실패 → `.FAILED.json` (종료코드 1)

Gemini 가 `max_attempts`(기본 4)회 만들어도 검증을 못 통과 → `register.py` 가 ① lite→full probe 재정찰 ② (본문 추출 실패였으면) 글페이지 render+HAR re-probe 후 강한 hint 로 재시도 → 그래도 안 되면 `.FAILED.json`. `last_feedback` 의 `[FAIL] <체크명>` 으로 어떤 케이스인지 판별.

### 2a. `[FAIL] posts_nonempty: 0건` / `[FAIL] fetch_list: ...` — 목록 추출 실패
- **원인**: ① `row_selector`(httpx_html) 또는 `list_path`(httpx_json) 가 틀림. ② **목록 자체가 JS 렌더** — 정적 HTML 에 글이 없음(SPA). ③ 목록 URL/파라미터가 잘못(엉뚱한 페이지를 받음). ④ 목록 HTML 은 정적으로 멀쩡한데 probe 가 "첫 글"을 사이드바/메뉴 링크로 잘못 집어서(`pick_first_article_url`) LLM 이 엉뚱한 글 URL 패턴을 보고 selector·검증이 다 어긋남 *(넥슨 포럼 케이스 — `board_list?board=1018` 에서 서브게시판 링크 `board_list?board=1618` 를 첫 글로 집음)*.
- **대응**: probe 의 `list_candidates.json` 의 `html_repeating_patterns` / `traffic_json_api_candidates` 를 보고 진짜 글 목록인 후보를 골라 손으로 `row_selector`/`list_path` 지정 → `register.py --config`. SPA 면 `strategy: "playwright_html"` + `list.wait_selector`(목록 행이 그려질 때까지 대기). 클릭/스크롤 후에야 목록이 로드되면(networkidle 만으론 안 잡힘) → 손어댑터. **④(probe 가 첫 글을 잘못 집음)면 자동 재시도가 효과 있을 수 있다**: `register.py "<목록URL>" --article-url "<실제 글 하나 URL>"`(또는 봇 `/preview`·`/watch` 의 `article_url` 인자) — first_article_url 을 교정하고 그 글페이지를 render+HAR 로 re-probe 한 뒤 강한 hint 와 함께 처음부터 재생성. (`config 기반 엔진 가이드.md` §4.)

### 2b. `[FAIL] article_body_len: post_id=... 0자 (<100 — content selector 의심)` — 목록은 OK, 본문 추출 실패
가장 흔함. `register.py` 가 자동으로 ②(글페이지 render+HAR re-probe → 본문 JSON API 후보가 있으면 `article.fetch_kind:"json"` config, 없으면 `playwright_html`)까지 시도했는데도 실패한 것. 원인 분류:
- **(i) 본문 selector 가 틀림 (정적 HTML 엔 본문이 있음)** — probe 의 `article.html` (또는 글페이지를 직접 `curl`)을 보고 본문 컨테이너 CSS 를 찾아 `article.content` 에 fallback chain 으로 지정 → `register.py --config`. (escalation 이 자동으로 못 맞춘 경우 — selector 후보가 애매하거나 본문이 여러 조각으로 나뉘어 있음.)
- **(ii) 본문이 SPA/JS 렌더 — 정적 HTML 에 아예 없음** — escalation 이 글페이지를 Playwright 로 렌더했는데도 본문이 안 나옴 (networkidle 후에야/스크롤 후에야 로드되거나, iframe 안이거나). → 본문을 주는 XHR 을 *대화형*으로 찾아야 함: 브라우저 DevTools → Network 켜고 그 사이트에서 글을 *클릭* → 본문(HTML/텍스트)을 담아오는 요청 URL/응답 구조 확인 → `article.url_template`(글 ID 자리 `{post_id}`) + `fetch_kind:"json"` + `content:[{from:"json", path:[...]}]` 손작성. (`probe/extract.py:traffic_article_body_candidates` 는 글페이지를 *직접* 열었을 때의 HAR 만 봄 — 직접 GET 이 안 되는 SPA 면 못 잡음.)
- **(iii) 목록의 글 링크 ≠ 직접 접근 가능한 글 URL** *(마비노기 모바일 케이스, 2026-05-11)* — 목록의 `<a href>` 는 `…/News/notice/View?threadId=3440249` 인데 직접 GET 하면 `/Main` 으로 302 튕김(= 클라이언트 라우트). 실제로 클릭하면 가는 `…/News/Notice/3440249` (경로형)은 직접 GET 시 200 + 본문이 정적 HTML 에 들어있음. → 자동 파이프라인은 페이지 HTML 어디에도 없는 URL 형을 추측 못 함. **손작성 config 에서 `url` 필드를 `{from:"template", value:"https://…/News/Notice/{post_id}"}` 로** (`post_id` 는 href 의 `threadId=(\d+)` 에서 추출), `article.content` 는 그 경로형 페이지의 본문 selector. → `register.py --config`. (예: `configs/mabinogimobile.nexon.com_News_notice.json`)
- **(iv) `skip_status` 케이스** — 일부 글이 401/403(접근 제한) 이면 그건 정상 — `article.skip_status:[401,403]` 두면 그 글은 본문 비워서 넘어가고 다른 글로 본문 검증. *모든* 글이 그러면 BLOCKED 쪽(§1).

### 2c. `[FAIL] published_at_iso: ISO8601 파싱 실패: ['2026.05.07T00:00:00+09:00', ...]` — 날짜 정규화 실패
- **원인**: Gemini 가 날짜 문자열(`2026.05.07` 등)을 ISO8601 로 못 바꿈 — 보통 점(`.`)을 안 고치고 시간만 붙임.
- **대응**: 보통 재시도에서 자동으로 고침. 안 되면 손으로 transform: `["replace",".","-"]` 후 `["date_only_to_iso","+09:00"]`, 또는 `["iso8601",["%Y.%m.%d"],"+09:00"]`. (날짜가 아예 없으면 `published_at` 필드를 빼도 됨 — 검증 통과함.)

### 2d. `[FAIL] post_id_stable_shape` / `post_id_unique` / `title_nonempty` — 필드 매핑 실수
- **원인**: `post_id` 로 공백 있는 문자열(제목을 잘못 씀)이나 매번 바뀌는 slug 를 씀 / `title` 셀렉터가 빈 값을 줌.
- **대응**: `post_id` 는 URL·href 안의 안정적인 숫자 ID 를 써라(새 글 감지의 키). 손으로 필드 셀렉터/transform 수정 → `register.py --config`.

### 2e. `생성 실패: gemini 호출/파싱 실패` — Gemini API 문제
- **`429 / RESOURCE_EXHAUSTED`**: 그 키 quota 소진 — 자동으로 다음 키로 폴백(`output/state/gemini_key_cursor` 로 라운드로빈). *모든* 키가 소진되면 명확히 에러. → `.env` `GEMINI_API_KEYS` 에 키 추가(콤마구분), 또는 유료 키.
- **`503 UNAVAILABLE "high demand"`**: Google 모델 과부하 — 일시적. 해당 시도 1회를 까먹음. → 잠시 후 재시도. (구조적 실패가 아니라 운 — 다른 [FAIL] 가 같이 안 보이면 그냥 다시 돌리면 됨.)
- **`스키마 검증 실패` 반복**: Gemini 가 자꾸 잘못된 config JSON 을 냄. 드뭄. → 손작성.

### 2f. `chromium 락 대기 초과` / `register.py 실행 시간 초과 (10분)` / `재-probe 실패`
- **원인**: register/poll/다른 `/watch` 가 동시에 chromium 을 쓰려 함 (락 대기) / 사이트가 너무 느림 / probe 가 멈춤.
- **대응**: 잠시 후 다시. 폴링 시각(매일 08:20 KST)과 겹쳤으면 그것만 피해도 됨. 계속 시간초과면 그 사이트가 비정상적으로 느린 것.

---

## 3. "되긴 됐는데 이상함" — 자동 등록은 성공했지만 품질 문제 (소프트 경고)

`.FAILED.json` 은 안 생기지만 `register.py` 출력의 `경고:` 줄, 또는 `last_feedback` 의 `[warn]`:
- `matches_probe_first_article: probe first_article_url=... 와 일치하는 글 URL 없음` — probe 가 헤더의 잡 링크(myinfo/login 등)를 first_article_url 로 잡았을 수 있음(2026-05-11 escalation 쪽은 점수 기반으로 고치긴 했음). 등록은 됐으니 폴링 결과를 한 번 확인.
- `article_body_chrome: content 에 <nav>+<footer> 둘 다 있음` — `article.content` 가 페이지를 통째로 긁었을 수 있음 → 더 좁은 selector 로 손수정 권장.
- `count_ballpark: N건 (probe 후보 child_count≈M)` 차이 큼 — 목록을 일부만 잡았거나 노이즈 행을 포함했을 수 있음.

---

## 4. 손작성으로 가는 경계선 — config(JSON) vs handwritten adapter(Python)

자동 실패 시 **손작성 config(JSON) 으로 충분한 경우**가 많다 — `register.py --config configs/<x>.json`:
- 본문 selector·날짜 transform·필드 매핑만 틀렸을 때 (probe 산출물 보고 고침).
- 본문이 단순 JS 렌더일 때 → `strategy:"playwright_html"` + `wait_selector` 짜리 config.
- 본문이 JSON API 로 올 때 → `httpx_json` 또는 `httpx_html`+`article.fetch_kind:"json"` config.
- 목록 링크와 실제 글 URL 이 다를 때 → `url` 필드를 `template` 로 (마비노기 케이스).

**진짜 `handwritten` adapter(`adapters/<site>.py`) 가 필요한 경우** — config 스키마로 표현이 안 될 때:
- Cloudflare 챌린지가 강해서 playwright-stealth + 특수 처리가 필요 (arca.live → `ArcaLiveAdapter`).
- 데이터가 클릭/스크롤/탭전환 후에야 로드 (networkidle 만으론 못 잡음).
- 본문이 여러 API 호출을 조합해야 나오거나, 인증/서명이 필요한 경우.
→ 절차는 `사이트 어댑터 추가 가이드.md`. `adapters/<site>.py` + `configs/<x>.json`(`strategy:"handwritten"`, `adapter`+`kwargs`) → `register.py --config`.

---

## 5. 미래 개선 아이디어

- ~~`register.py --article-url "<글URL>"` (+ 봇 `/preview`·`/watch` 의 `article_url` 인자) — probe 가 "첫 글"을 잘못 집는 사이트에서 사람이 진짜 글 URL 을 주면 first_article_url 교정 + 그 글페이지 render+HAR re-probe + 강한 hint.~~ → 구현됨(2026-05-12). `config 기반 엔진 가이드.md` §4. (그래도 추측 불가형 — 목록 링크와 직접접근 URL 이 아예 다른 마비노기류 §2b(iii) — 는 여전히 손작성 config.)
- `register.py --hint "<자유 텍스트>"` 같은 더 일반적인 사람-힌트 주입 — escalation_hint 로 직접 주입.
- 대화형 글페이지 probe (목록 띄움 → 글 링크 클릭 → 본문 렌더 대기 → HAR 캡처) — SPA 본문 API 자동 발견.
- `list-only` 등록 모드 — 본문을 못 얻는 사이트도 제목·날짜·링크만으로 등록(요약 없이). 현재는 `article.content` 가 빈 config 를 손작성해서 `--config` 로 우회 가능(검증을 안 거치므로).
