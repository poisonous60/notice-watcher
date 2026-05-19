---
slug: infra_catalog_batch_rev4_2026-05-19
url: (infra — catalog batch rev4 첫 실행 + 14 사이트 fix)
status: ✅ 42/42 등록 완료 (rev4 plan 끝)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [board_shape_gate_overreject, playwright_sw_assertion_crash, rss_xml_parser_mismatch, retry_unfixed_sites_wasteful, spa_inline_json_no_engine_support]
config_strategy: mixed
adapters_changed: []
engine_files_touched: [probe/discover.py, probe/fetch_headless.py, probe/fetch_headful.py, scripts/playwright_daemon.py, engine/extract_helpers.py, engine/strategies/httpx_html.py, engine/strategies/httpx_json.py, engine/config_schema.py, scripts/register_batch.py, scripts/remote.py, dashboard/candidates_view.py, dashboard/templates/candidates.html, configs/candidates/catalog.yaml]
tags: [catalog-batch, rev4, board-shape-gate, playwright-service-worker, rss-xml-parser, next-data-inline-json, hoyolab, discourse, riot-lol, namuwiki, epic-seven, onstove, blizzard]
requested_by: poisonous60
---

## 무엇이 일어났나

`docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` rev4 plan 의 §3~10 실행. catalog 42 사이트 N100 bot worker 가 일괄 enqueue → drain 첫 실행 시 28 registered / 8 gate_reject / 6 gen_fail. 이후 5 round 의 root-cause fix + 손-config 박아 42/42 등록 (100%).

### 초기 분포 (rev4 첫 batch run 결과)

| status | count | subkind |
|---|---|---|
| registered | 28 | (이미 자동등록되어 있던 사이트) |
| gate_reject | 8 | board_shape (RSS 5 + HoYoLAB 2 + Blizzard News) |
| gen_fail | 6 | posts_nonempty(3) / title_nonempty(1) / unknown(2) |

### 1차 retry 후 (--force 박은 직후)

board_shape 8 → 3, gen_fail 6 → 3, **새로 BUG 8건** (subprocess_timeout) 발생. → 사용자가 "왜 다시하냐" — root-cause 안 고친 사이트 retry 가 LLM 토큰 낭비 + 새 결함 surface.

## 왜

### 결함 root cause 5종

1. **RSS path 의 board_shape gate false-positive** — `_FEED_PATHS` (`{host}/rss`, `{host}/feed` 등) 는 호스트 *루트* 만 시도. catalog 의 `bbs.ruliweb.com/news/board/1001/rss`, `steamcommunity.com/groups/SteamClientBeta/rss/` 처럼 board-별 RSS path 는 못 잡음 → `feed_candidates=[]` → board_shape gate "게시판 형식 아님" 거부 (RSS 5건).

2. **Playwright Service Worker assertion crash** — daemon chromium 의 shared instance 안에서 다른 사이트 (hoyolab.com 의 `/serviceWorker.js`) 가 등록한 SW 가 새 context attach 시점 race 로 `CRBrowser._onAttachedToTarget` assertion 통과 못 함 → Node driver 죽고 register subprocess 의 stdout pipe block → 600s killer SIGKILL.
   - 첫 batch 에선 발생 X (HoYoLAB ×3 가 처음에는 board_shape 으로 거부됐기 때문에 SW 등록 안 됐음).
   - --force retry 에서 SW가 한 번 등록된 후 다음 사이트들 처리 시 stale SW target attach → 8 사이트 BUG.

3. **RSS XML 응답을 HTML parser 로 처리** — `engine/strategies/httpx_html.parse_list_html` 가 `BeautifulSoup(text, "lxml")` 으로 파싱. lxml HTML parser 는 `<link>` `<guid>` 같은 HTML void element 를 self-closing 으로 처리 → RSS 의 `<link>https://…</link>` 컨텐츠가 element 안 children 으로 못 들어감 → `it.find('link').get_text()` 빈 문자열 → post_id/url 추출 실패 → posts_nonempty=0.

4. **`--force` retry 가 root-cause 안 고친 사이트도 LLM 호출** — `register_batch.py --force` 는 catalog 전체 enqueue + 마커 삭제. 사용자가 직전 commit 에서 RSS gate 만 고쳤는데 retry 가 HoYoLAB/Blizzard/Riot/Epic7/namuwiki 9 사이트도 다시 LLM 호출. 사용자가 명시적으로 지적: "거부당한 거 다시하는거야? 그럼 거부당한 걸 고치고 다시 해봐야지 뭐하는거야 이게".

5. **SPA inline JSON 미지원** — Riot LoL News 는 외부 JSON XHR 없음. 데이터가 `<script id="__NEXT_DATA__">` 안에 inline. engine 의 `httpx_json` 은 응답 자체를 JSON parse 만 가능 — HTML 내부 script 추출 기능 X.

## 픽스

### 영구 게이트 (5 commits)

- `c550d2f` `probe/discover.py`: `_FEED_URL_RE` path 매칭 (`/rss/?`, `/feed/?`, `/feeds(/|$)`, `.rss/.atom/.xml`). 입력 URL 통과 시 candidates 에 self entry 박음. board_shape gate 의 feed_candidates 시그널 충족.
- `9d1dd56` `probe/fetch_headless.py` + `scripts/playwright_daemon.py`: launch arg `--disable-features=ServiceWorker` — chromium SW subsystem 차단. `service_workers="block"` context option 만으로는 *기존* SW target attach 못 막아서 daemon args 로 통째로 끔. systemctl --user restart notice-pw-daemon.service 필요.
- `42f9e3d` `engine/extract_helpers.parse_html_or_xml` + `httpx_html.parse_list_html`: text prefix `<?xml`/`<rss`/`<feed` 감지 → `BeautifulSoup(..., 'lxml-xml')` parser 분기. 일반 HTML 사이트엔 영향 X (auto-detection).
- `8e63b22` `engine/strategies/httpx_json` + `config_schema`: `list.script_root` (`{"selector": "script#__NEXT_DATA__"}`) 옵션. HTML 응답에서 지정 `<script>` body 를 JSON parse 해서 payload 로 사용.
- `bf065e5` `scripts/register_batch.py` + `remote.py`: `--url URL …` allowlist (반복 가능). catalog 안 URL 만 허용. `--force` 와 동시 사용 금지. 정책: root-cause 안 고친 사이트 retry 안 함.

### Hand-config (7 files)

- `host_us-forums-blizz_en_895a75b6.json` — Discourse `/latest.json` REST. topic_list.topics, `/t/{post_id}` URL pattern.
- `host_hoyolab-com_circles_{41251f69,5051fb8a,f742739b}.json` — `bbs-api-os.hoyolab.com getNewsList` gids=2/6/8. `x-rpc-language: ko-kr` header. post_id=post.post_id, URL=`/article/{post_id}`. published_at `unixtime_to_iso s`.
- `host_news-blizzard-c_en-us_ef8e0474.json` — `/api/news` Contentstack feed. list_path=feed.contentItems, properties.newsId/title/newsUrl/lastUpdated.
- `host_page-onstove-co_epicseven_1dd46993.json` — `api.onstove.com/cwms/v3.0/article_group/BOARD/995/article/list` (board_seq=995). value.list, article_id/title. published_at unixtime ms.
- `host_leagueoflegends_en-us_74f516a8.json` — script_root=`script#__NEXT_DATA__`, list_path=`props.pageProps.page.blades[2].items` (articleCardGrid). post_id 은 action.payload.url 의 last segment regex_extract. blade index 2 는 fragile — 사이트 reorder 하면 재등록 필요.
- `host_namu-wiki_RecentChanges_2370318a.json` — playwright_html, wait_selector + row_selector = `a[href^='/w/']`. obfuscated class 회피, anchor 자체가 row. published_at X (RecentChanges 의 timestamp 구조 obfuscated). body_empty_acceptable=true.

### Auto-fix 흡수 (6 RSS)

영구 게이트 fix 만으로 자동 등록: 루리웹 RSS ×4 (1001/1003/1004/300004), Steam Client Beta RSS, Steam Daily Deals RSS. `--url` allowlist 로 재시도.

### 부수 발견

- **ruliweb IP rate-limit**: 3 ruliweb URL concurrent retry 시 `ConnectTimeout` 일제 발생. ruliweb 가 N100 outbound IP 일시 차단. ~30분 대기 후 sequential retry 로 회복.
- **PyYAML 누락**: `requirements.txt` 에 없어 N100 venv `register_batch.py` 첫 실행 시 ImportError. dev 박스는 system python 으로 우연히 통과. commit `99f4341` 추가.

## fix_layer

F (전 layer 박힘): probe (C/D), engine (E), config (F), scripts (F), dashboard (G).

## 관련 case

per-site case stub:
- `host_us-forums-blizz_en_895a75b6.md`
- `host_hoyolab-com_circles_{41251f69,5051fb8a,f742739b}.md`
- `host_news-blizzard-c_en-us_ef8e0474.md`
- `host_page-onstove-co_epicseven_1dd46993.md`
- `host_leagueoflegends_en-us_74f516a8.md`
- `host_namu-wiki_RecentChanges_2370318a.md`

## 다음

- catalog rev4 워크플로 첫 cycle 완주. 새 사이트 추가 시 `dashboard /candidates "▶ batch run"` 또는 CLI `python scripts/register_batch.py` (default mode = untried-only enqueue) → bot worker drain → 분포 확인 → 필요 시 root-cause fix + `remote.py batch-register --url <fixed_url>` retry.
- ADR 후보: §12 의 3건. 사용자 결정.
