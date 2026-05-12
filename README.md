# crwalingTest — 게임 공지/게시판 크롤링: 정찰 도구 + 어댑터 + config 기반 자동 엔진

게임 공지·아카라이브 채널·디시인사이드 마이너 갤러리 등의 글을 수집하기 위한 작업 공간.
- **probe 도구** (`probe/`, `scripts/probe.py`): 크롤링 *전에* 사이트 접근 경로·request 입출력을 파악.
- **어댑터** (`adapters/`): 사이트별로 손으로 짠 수집기 (모두 async, `BaseAdapter` 상속).
- **config 기반 엔진** (`engine/` + `generate/` + `scripts/register.py`,`poll.py`): 경량 LLM(Gemini)이 probe 결과를 보고 **선언적 config(JSON)** 를 작성 → 범용 엔진이 실행 → 자동 검증/재시도 → 폴링·새 글 감지·깨짐 시 재-probe. → **[docs/config 기반 엔진 가이드.md](docs/config%20기반%20엔진%20가이드.md)**

## 디렉토리 구조

```
crwalingTest/
├── docs/                       # 가이드/지침 문서 (모두 읽기)
│   ├── 프로젝트 개요.md
│   ├── 크롤링 지침.md                   # 안전 운영 (§6 = config 엔진의 정책 적용)
│   ├── 사이트별 구현 방침.md
│   ├── 사이트 어댑터 추가 가이드.md      # ← 손으로 어댑터 추가 시 표준 워크플로우
│   ├── config 기반 엔진 가이드.md        # ← config 자동 생성·실행·폴링 워크플로우
│   ├── 배포 가이드.md                    # ← N100 미니PC + Discord 봇 + systemd 상시 운영
│   ├── 게임 공지사항 ... 종합 조사.md
│   └── ...
│
├── bot/                        # Discord 봇 (discord.py): /watch /preview /list /unwatch /status
│   ├── main.py                 # 게이트웨이 봇 + 슬래시 명령 (register.py 를 subprocess 로)
│   ├── url_gate.py             # /watch·/preview(처음 보는 사이트) probe 전단 URL 게이트 — 구조검증/SSRF/SNS·축약·파일 블랙리스트/Safe Browsing(v4). 단독 실행: python -m bot.url_gate "<url>"
│   ├── db.py                   # SQLite — 구독(필터·스케줄·대상) / 다이제스트 대기열 / 발송 기록
│   ├── discord_rest.py         # 봇 토큰으로 Discord REST 직접 (notify.py 가 발송에 사용)
│   └── config.py               # .env 로드 + BOT_TOKEN/OWNER_USER_ID/GUILD_ID/SAFE_BROWSING_API_KEY
├── deploy/                     # systemd 유닛 + .env.example (배포 가이드 참고)
│
├── probe/                      # 사이트 정찰 도구 패키지
├── adapters/                   # 사이트별 손어댑터 (모두 async)
│   ├── base.py                 # BaseAdapter / NoticePost / polite_sleep
│   ├── runner.py               # collect_parallel() — 사이트 단위 병렬 오케스트레이터 (config 어댑터도 동일 취급)
│   ├── endfield.py / arca.py / dcinside.py / skku_cse.py / navercafe.py
│
├── engine/                     # ← config 해석 엔진 (두꺼운 SDK)
│   ├── config_schema.py        # config JSON 스키마 + validate_config
│   ├── transforms.py           # 닫힌 transform 라이브러리 + apply_chain
│   ├── extract_helpers.py      # field source(css/attr/json/const/template/concat/class_present) + fallback chain
│   ├── config_adapter.py       # ConfigAdapter(BaseAdapter) + make_adapter + load_config
│   ├── strategies/             # httpx_html / httpx_json / playwright_html
│   ├── digest.py               # probe 산출물 → gemini 입력 digest (clean_html 포함)
│   └── base_compat.py
│
├── generate/                   # ← probe digest → config (Gemini)
│   ├── gemini.py               # Gemini REST + 다중 API 키 자동 로테이션
│   ├── prompt.py               # 시스템 지침(포맷 스펙) + few-shot(configs/*.json) + build_user/retry_prompt
│   ├── generator.py            # generate_config(1-shot) / generate_config_validated(검증+재시도 루프)
│   └── validate.py             # validate_built_config — 3층위 실행 검증
│
├── configs/                    # 생성/등록된 config + few-shot 레퍼런스 config (커밋 대상)
│
├── scripts/                    # CLI 진입점
│   ├── probe.py                # python scripts/probe.py "<URL>" [--lite]
│   ├── register.py             # URL → probe → digest → gemini → config + baseline   (또는 --config <path> 로 손작성 config 등록)
│   ├── triage.py               # 봇(N100)에서 자동 등록 실패한 사이트 모아오기: pull|list|show <slug> → 손 config 처리 (skill: hand-config)
│   ├── poll.py                 # 등록된 사이트 폴링 + 새 글 감지 + 깨짐 시 재-probe
│   ├── notify.py               # collected/<ts>/<slug>.new.json → Gemini 요약 → Discord 발송 (Phase1: webhook + delivered.json)
│   ├── poll_and_notify.py      # poll.py → notify.py 한 번에 (systemd 가 실행) — chromium 락 안에서
│   ├── _chromium_lock.py       # chromium 띄우는 작업끼리 동시 실행 방지 파일 락
│   ├── gen_config.py           # URL → config 만 (수동/디버그)
│   ├── collect_all.py          # 5개 손어댑터 병렬 수집 (구식 데모)
│   ├── demo_config.py          # config 검증/실행/원본 산출물 비교
│   ├── gate_check.py / verify_m1.py / demo_*.py   # (개발용)
│
├── .claude/skills/hand-config/ # ← 스킬: 링크 → 손 config 작성·등록·N100 배포 / 실패한 preview triage 워크플로우
├── experiments/ · reference/
├── output/                     # 모든 산출물 (gitignore)
│   ├── probe/<slug>/           # probe 결과 (HAR/HTML/summary/list_candidates...)
│   ├── adapter/<site>/         # 어댑터 데모 결과
│   ├── poll_state/<slug>.json  # 등록 상태 + 본 글 post_id 집합 + 깨짐 카운터 (.FAILED.json = 자동등록 실패)
│   ├── triage_queue.jsonl      # 봇이 자동등록 실패한 /preview·/watch 한 줄씩 기록 (scripts/triage.py 가 읽음)
│   ├── collected/<ts>/         # 폴링 결과 (summary.txt + <slug>.new.json)
│   └── state/<slug>.json       # 로그인 storage_state
│
├── requirements.txt
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

배포(N100 미니PC에 systemd 로 상시 + Discord 봇 `/watch` 로 사이트 등록): **[docs/배포 가이드.md](docs/배포%20가이드.md)**.

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

## 어댑터 5종 현황 (모두 async)

| 어댑터 | host | 진입 | polite_sleep 기본 | 로그인 |
|---|---|---|---|---|
| `EndfieldAdapter` | `web-news.gryphline.com` | httpx.AsyncClient (JSON API) | 2~5s | 불필요 |
| `DCInsideMGalleryAdapter` | `gall.dcinside.com` | httpx.AsyncClient (HTML) | **30~35s** (robots) | 비로그인 갤만 |
| `ArcaLiveAdapter` | `arca.live` | playwright.async_api stealth | 2~5s | 성인 채널만 (storage_state) |
| `SkkuCseAdapter` | `cse.skku.edu` | httpx.AsyncClient (HTML) | 2~5s | 불필요 |
| `NaverCafeAdapter` | `naver.com:cafe` | httpx.AsyncClient (JSON API) | 2~5s | 비공개 글은 자동 스킵 |

`scripts/collect_all.py` 가 5개를 `asyncio.gather` 로 병렬 실행. 같은 host 어댑터는 자동 직렬화되므로 dcinside 갤러리 두 개를 동시에 등록해도 Crawl-Delay 가 깨지지 않는다.

## 정책 요약

- 요청 간 간격은 엔진/어댑터가 항상 강제 (기본 3~6s + jitter, 같은 host 직렬화). robots `Crawl-Delay` 는 config 의 `polite_sleep` 로 반영하고 엔진은 그 값을 *하한* 으로 쓴다(런타임마다 robots 재독·사이트별 클램핑은 안 함 — 이번 스코프 밖).
- robots `Disallow` 는 등록 시 경고만 띄우고 진행. `LOGIN_REQUIRED` / `BLOCKED_*` 사이트는 자동 등록 거부.
- 로그인은 사용자가 한 번 (Playwright headful → `state.json` 재사용); 자동 로그인은 안 함. 차단 우회(TLS fingerprint / IP 로테이션 / CAPTCHA)는 자동 경로에서 일절 안 함.
- 요약본만 푸시, 원문 그대로 재배포 금지 (다운스트림 요약·알림 컴포넌트 책임).

자세한 내용: `docs/크롤링 지침.md` (§6 = config 엔진의 정책 적용) + `docs/config 기반 엔진 가이드.md` + `docs/사이트별 구현 방침.md`.
