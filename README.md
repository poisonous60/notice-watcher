# notice-watcher — 게임 공지/게시판 크롤링: 정찰 도구 + 어댑터 + config 기반 자동 엔진

게임 공지·아카라이브 채널·디시인사이드 마이너 갤러리 등의 글을 수집하기 위한 작업 공간.
- **probe 도구** (`probe/`, `scripts/probe.py`): 크롤링 *전에* 사이트 접근 경로·request 입출력을 파악.
- **어댑터** (`adapters/`): 사이트별로 손으로 짠 수집기 (모두 async, `BaseAdapter` 상속).
- **config 기반 엔진** (`engine/` + `generate/` + `scripts/register.py`,`poll.py`): 경량 LLM(Gemini)이 probe 결과를 보고 **선언적 config(JSON)** 를 작성 → 범용 엔진이 실행 → 자동 검증/재시도 → 폴링·새 글 감지·깨짐 시 재-probe. → **[docs/config 기반 엔진 가이드.md](docs/config%20기반%20엔진%20가이드.md)**

## 디렉토리 구조

```
notice-watcher/
├── docs/                       # 가이드·지침·설계 문서
│   └── cases/                  # ← 사이트별 등록 시도 사례 (hand-config skill 이 작성·갱신)
│                               #    INDEX.md 는 `python scripts/cases_index.py` 자동 생성
│
├── bot/                        # Discord 봇 (discord.py): /watch /preview /list /unwatch /status /report …
│   ├── main.py                 # 게이트웨이 봇 + 슬래시 명령 (register 잡 enqueue)
│   ├── worker.py               # 잡 큐 워커 — register.py / poll.py 를 chromium_lock 안에서 subprocess
│   ├── admin.py                # owner 전용 명령 (구독 강제 삭제, dump 등)
│   ├── inspector.py            # config + 최근 poll 결과 진단 ("왜 이 글 안 보내?")
│   ├── site_ops.py             # /watch·/preview·/unwatch 공통 routine — gate → enqueue → ack 진행 갱신
│   ├── case_runs_meta.py       # 잡 enqueue/dequeue 시 case_log 메타(트리거 사용자/길드 등) 기록
│   ├── runtime_config.py       # config.toml + config.local.toml 로더 (캐시 X — import 시 1회)
│   ├── url_gate.py             # /watch·/preview(처음 보는 사이트) probe 전단 URL 게이트 — 구조검증/SSRF/정책 블랙리스트/Safe Browsing(v4). 단독 실행: python -m bot.url_gate "<url>"
│   ├── url_blacklist.json      # 위 게이트 2단계 블랙리스트 — groups[] {name, message, host_suffix[], path_ext[]}. 편집 즉시 반영
│   ├── db.py                   # SQLite — 구독·잡 큐·rate_limit·deliveries·feedback·reports
│   ├── discord_rest.py         # 봇 토큰으로 Discord REST 직접 (notify.py 가 발송에 사용)
│   └── config.py               # .env 로드 + BOT_TOKEN/OWNER_USER_ID/GUILD_ID/SAFE_BROWSING_API_KEY
│
├── dashboard/                  # ← dev 박스 전용 FastAPI 대시보드 (127.0.0.1:8765, owner 1인용·인증 X)
│   ├── app.py                  # 라우터 — /subs /jobs /reports /control /usage /cases /timings /users 등
│   ├── cases_view.py           # case_log audit 쿼리/필터 (skill 실행 retrospect)
│   ├── control_actions.py      # /control 페이지 — runtime config 토글 (rate_limit/prune/concurrency 등) + LLM routing
│   ├── usage_view.py           # 토큰/비용 조회 (usage_recorder JSONL → KRW + USD)
│   ├── tracing_view.py         # per-phase span 트리 뷰 (engine.tracing JSONL)
│   ├── user_view.py · prompts.py · actions.py · state.py · shell.py
│   └── templates/ · static/    # Jinja2 + HTMX 부분 갱신
│
├── deploy/                     # systemd 유닛 + .env.example (배포 가이드 참고)
│   ├── notice-bot.service      # Discord 봇 (상시)
│   ├── notice-poll.service · .timer    # 폴링 주기 트리거
│   └── notice-notify.service · .timer  # 알림 주기 트리거
├── systemd/
│   └── notice-pw-daemon.service        # 사용자 unit — chromium daemon (dev 박스 옵션)
│
├── probe/                      # 사이트 정찰 패키지 (fetch_static/fetch_headless/fetch_headful, hydration, signals, diagnose, …)
├── adapters/                   # 사이트별 손어댑터 (모두 async, BaseAdapter 상속)
│   ├── base.py                 # BaseAdapter / NoticePost / polite_sleep
│   ├── runner.py               # collect_parallel() — 사이트 단위 병렬 오케스트레이터
│   └── endfield.py / arca.py / dcinside.py / skku_cse.py / navercafe.py / daumcafe.py / reddit.py
│
├── engine/                     # ← config 해석 엔진 (두꺼운 SDK)
│   ├── config_schema.py        # config JSON 스키마 + validate_config
│   ├── transforms.py           # 닫힌 transform 라이브러리 + apply_chain
│   ├── extract_helpers.py      # field source(css/attr/json/const/template/concat/class_present) + fallback chain
│   ├── config_adapter.py       # ConfigAdapter(BaseAdapter) + make_adapter + load_config
│   ├── strategies/             # httpx_html / httpx_json / playwright_html
│   ├── recognizers/            # 알려진 플랫폼 URL → slug + canonical board (arca / dcinside / naver_cafe / naver_game_lounge / nexon_forum / daum_cafe / reddit)
│   ├── known_platforms.py      # recognizer 디스패치 + post-register validate (룰 D 의 slug schema 마이그)
│   ├── slug.py                 # url_to_slug (configs·poll_state·probe·bot.sqlite3 공통 키)
│   ├── tracing.py              # per-phase / per-attempt child span (output/tracing/*.jsonl)
│   ├── _tracking_query.py      # ?utm_… 같은 tracking 쿼리 정규화 (slug 안정화)
│   ├── digest.py               # probe 산출물 → LLM 입력 digest (clean_html 포함)
│   └── base_compat.py
│
├── generate/                   # ← probe digest → config (LLM)
│   ├── llm_base.py             # LLMClient 추상 + UsageRecord
│   ├── gemini.py               # Gemini REST + 다중 API 키 자동 로테이션
│   ├── openrouter.py           # OpenRouter REST (Claude / GPT / 기타)
│   ├── routing.py              # call_site → (provider, model) 디스패치 (output/llm_routing.json)
│   ├── usage_recorder.py       # 토큰/비용 JSONL append (output/usage/*.jsonl)
│   ├── prices.py               # model_prices.json 기반 USD 비용 계산
│   ├── prompt.py / prompts.py  # build_user/retry/system 빌더 + few-shot 로더
│   ├── generator.py            # generate_config(1-shot) / generate_config_validated(검증+재시도 루프)
│   └── validate.py             # validate_built_config — 3층위 실행 검증
│
├── prompts/                    # ← LLM 시스템/유저 프롬프트 텍스트 (외부화 — 핫 편집 + 대시보드 /control)
│   ├── config_writer.{system,user_skeleton,retry_skeleton}.txt
│   └── notify_{summary,filter}.{system,user}.txt
│
├── configs/                    # 생성/등록된 config + few-shot 레퍼런스 config (커밋 대상)
├── config.toml                 # ← 운영 튜닝값 (concurrency / rate_limit / chromium_lock / prune / register …)
├── config.local.toml           # ← (옵션) 머신별 override — gitignore
├── model_prices.json           # ← LLM 모델별 input/output USD/Mtok (prices.py 가 사용)
│
├── scripts/                    # CLI 진입점
│   ├── probe.py                # python scripts/probe.py "<URL>" [--lite]
│   ├── probe_smoke.py          # pre-push hook 이 stage 3·5 자동 실행 (회귀 차단)
│   ├── register.py             # URL → probe → digest → LLM → config + baseline   (또는 --config <path> 로 손-config 등록)
│   ├── triage.py               # 봇 운영 중 자동 등록 실패한 사이트 pull|list|show <slug> → 손 config (skill: hand-config)
│   ├── poll.py                 # 등록된 사이트 폴링 + 새 글 감지 + 깨짐 시 재-probe + post-register validate
│   ├── notify.py               # collected/<ts>/<slug>.new.json → LLM 요약·필터 → Discord 발송
│   ├── poll_and_notify.py      # poll.py → notify.py 한 번에 (systemd 가 실행) — chromium 락 안에서
│   ├── playwright_daemon.py    # ← chromium 데몬 (CDP attach) — probe cold launch (~2-3s) 회피
│   ├── _chromium_lock.py       # chromium 띄우는 작업끼리 동시 실행 방지 파일 락
│   ├── case_log.py             # ← skill 실행 audit 로그 (output/cases.sqlite3, hand-config 마지막 단계)
│   ├── cases_index.py          # docs/cases/*.md → docs/cases/INDEX.md 자동 생성
│   ├── dashboard.py            # ← `python scripts/dashboard.py` — uvicorn 으로 dashboard.app:app
│   ├── announce.py             # owner → 모든 구독자/관리자에 공지 발송
│   ├── push.py                 # dev box → 운영 호스트 ssh pull + restart 한방
│   ├── remote.py               # 운영 호스트 원격 진단 (ssh wrap)
│   ├── replay.py               # output/probe/<slug>/ 산출물 재생 (검증·디버그)
│   ├── inspect_subs.py         # bot.sqlite3 구독/잡 sqlite3 dump
│   ├── prune_probe.py          # output/probe·collected·tracing 디스크 pruning (cron)
│   ├── migrate_slug_schema.py  # 룰 D — recognizer 패턴 변경 시 configs/·poll_state·bot.sqlite3 일괄 rename
│   ├── gen_config.py           # URL → config 만 (수동/디버그)
│   ├── collect_all.py          # 손어댑터 병렬 수집 (구식 데모)
│   ├── demo_config.py          # config 검증/실행/원본 산출물 비교
│   ├── setup-hooks.{sh,ps1}    # .git/hooks/pre-push 박음 (probe_smoke 강제)
│   └── pre-push.sh             # pre-push hook 본체
│
├── tests/                      # pytest — probe heuristics / recognizers / bot / llm / inspector
├── .claude/skills/             # 자율 워크플로 스킬
│   ├── hand-config/            # 자동 등록 실패 사이트 손-config + 배포
│   ├── pipeline-rot-review/    # prompts/probe heuristics/cases 누적 rot 진단 (read-only)
│   └── report-triage/          # 사용자 /report 자동 진단 → 수정 → 배포
├── .claude/agents/             # 서브에이전트 정의 (hand-config-reviewer 등)
├── output/                     # 모든 산출물 (gitignore)
│   ├── probe/<slug>/           # probe 결과 (HAR/HTML/summary/list_candidates/diagnosis...)
│   ├── adapter/<site>/         # 어댑터 데모 결과
│   ├── poll_state/<slug>.json  # 등록 상태 + post_id 집합 + 깨짐 카운터 (.FAILED.json·.REJECTED.json = 자동등록 실패/거부)
│   ├── triage_queue.jsonl      # 봇이 자동등록 실패한 /preview·/watch 한 줄씩 기록
│   ├── collected/<ts>/         # 폴링 결과 (summary.txt + <slug>.new.json)
│   ├── tracing/*.jsonl         # engine.tracing per-phase span (대시보드 /timings 가 읽음)
│   ├── usage/*.jsonl           # usage_recorder LLM 호출 토큰/비용 (대시보드 /usage)
│   ├── cases.sqlite3           # case_log audit DB (skill 실행 retrospect, dev 박스 only)
│   ├── llm_routing.json        # routing.py source — 대시보드 /control 에서 편집
│   ├── playwright_daemon/      # chromium daemon endpoint·pid·log
│   └── state/<slug>.json       # 로그인 storage_state
│
├── requirements.txt
├── requirements-dashboard.txt   # FastAPI/uvicorn/jinja2/htmx — 대시보드만
└── .gitignore
```

## Quickstart

```bash
# 1) 의존성 설치 (1회)
pip install -r requirements.txt
playwright install chromium

# 2) 사이트 정찰
python scripts/probe.py "https://gall.dcinside.com/mgallery/board/lists/?id=endfield"
python scripts/probe.py "https://arca.live/b/akendfield" --login
python scripts/probe.py "https://endfield.gryphline.com/ko-kr/news"

# 3) 산출물 확인
#    output/probe/<slug>/summary.txt           ← 1페이지 요약
#    output/probe/<slug>/traffic.har           ← Chrome DevTools에서 열기
#    output/probe/<slug>/list_candidates.json  ← html_repeating_patterns(href_is_js/row_data_attrs 포함) / traffic_json_api_candidates(relevance_score 순) / inline_js_data_candidates(var X=[…] · X.push({…}) · <script type=application/json>) / first_article_url
#    output/probe/<slug>/article_click.{html,json} + traffic.article_click.har  ← 목록에서 글 링크를 실제로 클릭한 결과(직접 GET 으론 다른 데로 튕기는 클라이언트 라우트·href=javascript: 목록 진단용; --no-article-click 로 끔)

# 4) 어댑터 데모 (개별)
python scripts/demo_endfield.py
python scripts/demo_arca.py
python scripts/demo_dcinside.py
python scripts/demo_navercafe.py

# 5) 전체 사이트 병렬 수집 (asyncio.gather, 손어댑터)
python scripts/collect_all.py --articles --limit 3
```

## config 기반 자동 워크플로우 (권장 — Gemini 가 config 작성)

```bash
# Gemini 키: 환경변수 GEMINI_API_KEYS=키1,키2,... (여러 개면 429 시 자동 전환)  또는 GEMINI_API_KEY=키  또는 파일 GEMINI_API_KEY.md
# 모델: 기본 gemini-2.5-flash. 다른 모델: GEMINI_MODEL=gemini-3-flash-preview 등.

# 1) 사이트 등록 — URL 하나만 주면 probe → digest → gemini → config 생성 + 검증/재시도 + baseline 저장
python scripts/register.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="
#   → configs/<slug>.json + output/poll_state/<slug>.json   (실패 시 <slug>.FAILED.json + "손어댑터 작성 필요" 안내)

# 손으로 짠 config(handwritten strategy 등)를 그대로 등록 (probe/gemini 생략)
python scripts/register.py --config configs/arca_akendfield.json

# 2) 폴링 — 등록된 사이트 전부: config 실행 → post_id diff 로 새 글 → output/collected/<ts>/, 깨짐 연속 2회 시 자동 재-probe
python scripts/poll.py
python scripts/poll.py --sites <slug> --max-new-articles 5 --no-reprobe

# (디버그) probe → digest → config 만
python scripts/probe.py "<URL>" --lite
python -m engine.digest "<probe-slug>" --out digest.json
python scripts/gen_config.py "<URL>" --escalate --sanity
python scripts/demo_config.py --check-all          # configs/*.json 전부 검증
```

자세한 내용: **[docs/config 기반 엔진 가이드.md](docs/config%20기반%20엔진%20가이드.md)** (config 스키마 / transform 목록 / strategy / 검증 3층위 / 깨짐 처리).

## 알림 (Discord) — `notify.py` / `poll_and_notify.py`

폴링이 모은 새 글(`output/collected/<ts>/<slug>.new.json`)을 Gemini 로 요약해서 Discord 로 보낸다.

```bash
# 발송 대상: output/notify_targets.json = { "<slug>": "<discord webhook url>", ... }   (없으면 dry-run)
#   slug 는 poll_state 파일명과 같음 (예: "gall.dcinside.com_mgallery_board_lists_id_endfield")
python scripts/notify.py --dry-run          # 발송 안 하고 메시지만 출력
python scripts/notify.py                     # webhook 발송 + output/delivered.json 에 (slug,post_id) 기록 → 재실행 시 재발송 X

python scripts/poll_and_notify.py            # poll.py → notify.py 한 번에 (운영용; systemd notice-poll.service 가 이걸 실행)
```

배포(systemd 로 상시 폴링 + Discord 봇 `/watch` 로 사이트 등록): **[docs/배포 가이드.md](docs/배포%20가이드.md)**.

## 새 사이트 추가 (어떤 길로?)

- **먼저 `register.py "<URL>"` 자동 생성을 시도** — 대부분의 정적 HTML / JSON API 게시판은 Gemini 가 config 를 만들어낸다.
- 자동이 실패하면(`*.FAILED.json` + 안내) **`docs/사이트 어댑터 추가 가이드.md` 의 5단계로 손어댑터 작성** → `configs/<name>.json` 에 `strategy:"handwritten"` config 로 감싸 `register.py --config` 로 등록 → poll 파이프라인에 합류.

### (손어댑터) 5단계

`docs/사이트 어댑터 추가 가이드.md` 참고. 5단계:

1. `python scripts/probe.py "<URL>"` 로 정찰
2. `output/probe/<slug>/summary.txt` 검증
3. 진입 매트릭스 → 어댑터 진입 전략 결정
4. `adapters/<site>.py` 작성 (`BaseAdapter` 상속, `fetch_list`/`fetch_article` 구현)
5. `scripts/demo_<site>.py` 만들어 검증

## 어댑터 7종 현황 (모두 async, BaseAdapter 상속)

| 어댑터 | host | 진입 | polite_sleep 기본 | 로그인 |
|---|---|---|---|---|
| `EndfieldAdapter` | `web-news.gryphline.com` | httpx.AsyncClient (JSON API) | 2~5s | 불필요 |
| `DCInsideMGalleryAdapter` | `gall.dcinside.com` | httpx.AsyncClient (HTML) | **30~35s** (robots) | 비로그인 갤만 |
| `ArcaLiveAdapter` | `arca.live` | playwright.async_api stealth | 2~5s | 성인 채널만 (storage_state) |
| `SkkuCseAdapter` | `cse.skku.edu` | httpx.AsyncClient (HTML) | 2~5s | 불필요 |
| `NaverCafeAdapter` | `naver.com:cafe` | httpx.AsyncClient (JSON API) | 2~5s | 비공개 글은 자동 스킵 |
| `DaumCafeAdapter` | `cafe.daum.net` | httpx.AsyncClient (HTML) | 2~5s | 비공개 게시판 자동 스킵 |
| `RedditAdapter` | `reddit.com` | httpx.AsyncClient (`.json` API) | 2~5s | 불필요 (subreddit·flair 필터 지원) |

`scripts/collect_all.py` 가 손어댑터를 `asyncio.gather` 로 병렬 실행. 같은 host 어댑터는 자동 직렬화 → dcinside 갤러리 두 개를 동시에 등록해도 Crawl-Delay 안 깨짐.

운영 폴링은 `scripts/poll_and_notify.py` 가 손어댑터 + config 어댑터 양쪽을 같은 큐로 처리 (chromium 어댑터는 `_chromium_lock` 직렬화).

## 대시보드 (dev 박스 전용)

```bash
pip install -r requirements-dashboard.txt
python scripts/dashboard.py            # http://127.0.0.1:8765
```

owner 1인용·localhost 한정·인증 0. 페이지: `/subs` `/jobs` `/reports` `/control` `/usage` `/cases` `/timings` `/users`.

- `/control` — `config.toml` 의 runtime 값(rate_limit, prune cron, concurrency, register.max_attempts) 토글 + LLM routing(`output/llm_routing.json`) + prompt 텍스트(`prompts/*.txt`) 핫 편집.
- `/usage` — LLM 호출 토큰/비용 (USD + KRW). `output/usage/*.jsonl` 가 source.
- `/cases` — `output/cases.sqlite3` 의 skill 실행 audit (hand-config retrospect).
- `/timings` — `output/tracing/*.jsonl` 의 per-phase / per-attempt span 트리.

자세한 내용: **[docs/대시보드 가이드.md](docs/%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C%20%EA%B0%80%EC%9D%B4%EB%93%9C.md)**.

## Chromium 데몬

probe 의 cold launch (~2-3s) 회피 + worker pool 동시 진입 시 chromium 컨텍스트 share. CDP endpoint
띄워두고 probe 가 `connect_over_cdp` 로 attach.

```bash
python scripts/playwright_daemon.py             # foreground 시작
python scripts/playwright_daemon.py status      # 상태
python scripts/playwright_daemon.py stop        # graceful stop

# systemd user unit (장기 운영 시):
systemctl --user enable --now notice-pw-daemon.service
```

idle 정책: `IDLE_TIMEOUT_S` 미사용 시 자기 자신 stop. endpoint 파일 없으면 probe fresh launch — backwards-compatible. 장기 운영은 `--no-idle` 로 상시 가동.

## LLM routing (Gemini ↔ OpenRouter)

call_site 별로 provider/model 분리. source: `output/llm_routing.json`.

```json
{
  "config_generate":  "gemini:gemini-2.5-flash",
  "config_retry":     "gemini:gemini-2.5-pro",
  "notify_summarize": "openrouter:google/gemini-flash-1.5-8b",
  "notify_filter":    "openrouter:google/gemini-flash-1.5-8b",
  "_default":         "gemini:gemini-2.5-flash"
}
```

- 파일 mtime 캐시 — 대시보드에서 저장 즉시 반영 (재시작 X).
- 토큰/비용 자동 기록 → `output/usage/*.jsonl` → 대시보드 `/usage`.
- `model_prices.json` 에 USD/Mtok 정의 (없는 모델은 비용 0).

## 자가개선 워크플로 (skill: hand-config)

자동 등록 실패 사이트(`*.FAILED.json` + `triage_queue.jsonl`)는 `.claude/skills/hand-config/SKILL.md` 절차로 처리:

1. probe → 실패 진단 → 트랙 A(손-config 작성)·트랙 B(probe 일반화) 둘 다 의무
2. `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py`
3. `Agent(subagent_type='hand-config-reviewer', model='sonnet')` 자가 점검
4. dev 박스 commit → push (pre-push hook = `probe_smoke --stage 3 --stage 5` 강제)
5. 운영 호스트 ssh pull + bot restart
6. `python scripts/case_log.py log …` 로 audit (`output/cases.sqlite3`) — 대시보드 `/cases` 에서 retrospect

설계: **[docs/자가개선 인프라 계획.md](docs/%EC%9E%90%EA%B0%80%EA%B0%9C%EC%84%A0%20%EC%9D%B8%ED%94%84%EB%9D%BC%20%EA%B3%84%ED%9A%8D.md)** (rev 3).

## 정책 요약

- 요청 간 간격은 엔진/어댑터가 항상 강제 (기본 3~6s + jitter, 같은 host 직렬화). robots `Crawl-Delay` 는 config 의 `polite_sleep` 로 반영하고 엔진은 그 값을 *하한* 으로 쓴다.
- robots `Disallow` 는 등록 시 경고만 띄우고 진행. `LOGIN_REQUIRED` / `BLOCKED_*` 사이트는 자동 등록 거부 → `*.REJECTED.json` 마커.
- 로그인은 사용자가 한 번 (Playwright headful → `state.json` 재사용); 자동 로그인은 안 함. 차단 우회(TLS fingerprint / IP 로테이션 / CAPTCHA)는 자동 경로에서 일절 안 함.
- 요약본만 푸시, 원문 그대로 재배포 금지 (notify 컴포넌트 책임).
- **Rate limit** (`config.toml [rate_limit]`): 사용자당 시간/일 register 잡 상한 + 워커 큐 전역 상한 — 초과 시 사용자에 안내 후 enqueue 거부. 비공개·LOGIN_REQUIRED 사이트 100개 던짐 → chromium_lock 직렬 + LLM 비용 폭증 시나리오 차단.
- **Post-register safety** (`scripts/poll.py` + `engine/known_platforms.py`): 등록 후에도 known-platform validate / no-recognize 시 reprobe / body drift 감지 — silent 결함 3종 방어 (commit 79abc9f).
- **Disk prune** (`scripts/prune_probe.py`, `config.toml [prune]` cron): `output/probe·collected·tracing` 누적 차단.

자세한 내용: `docs/크롤링 지침.md` (§6) + `docs/config 기반 엔진 가이드.md` + `docs/사이트별 구현 방침.md`.
