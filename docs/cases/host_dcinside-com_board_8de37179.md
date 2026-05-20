---
slug: host_dcinside-com_board_8de37179
url: https://m.dcinside.com/board/stock
status: ✅ 플랫폼 인식기 추가 (디시 정식갤 m.dcinside.com/board/<id> 자동 등록)
outcome: handcrafted
date: 2026-05-20
fix_layer: F
failure_keys: [fetch_list_404, llm_url_rewrite, known_platform_unrecognized]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/dcinside_main.py]
tags: [recognizer, dcinside, platform-generalization, batch-2026-05-20-b]
requested_by: catalog 2026-05-20-b
---

## 무엇이 일어났나

batch 2026-05-20-b 에 디시인사이드 정식갤 모바일 보드 5건 (`m.dcinside.com/board/{programming,
nikke,umamusume,stock,baseball_new11}`). 결과 비일관: baseball 등록 OK, stock gen_fail,
nikke/uma nav-only reject, programming timeout.

stock 실패:

> [FAIL] fetch_list: HTTPStatusError '404 Not Found' for url
> 'https://m.dcinside.com/board/lists?id=stock&page=1'

## 진단 (분기 2a — known platform 인식기 누락)

기존 `dcinside_mgallery` 인식기는 **미니/마이너갤** (`gall.dcinside.com/mgallery/...`) 만 매칭.
정식갤 모바일 (`m.dcinside.com/board/<id>`) 은 미커버 → probe→LLM 경로. LLM 이 mobile board URL 을
desktop `/board/lists/?id=` 로 rewrite → mobile host 에 그 path 없어 404. baseball 만 우연히
맞는 config 생성, 나머지 비일관 실패. (probe top-candidate 는 `tbody.listwrap2 > tr.ub-content.us-post`
+ `href=/board/view/?id=stock&no={n}` 로 정상 list 를 이미 봄.)

재시도(저부하)에서 stock 은 LLM 이 맞는 config 생성 → rc=0. 즉 httpx_html 로 풀리지만
**비결정적** — 인식기로 고정 필요.

## 트랙 B (영구) = 트랙 A (즉시)

`engine/recognizers/dcinside_main.py` 신규. `m.dcinside.com/board/<id>` (+ desktop
`gall.dcinside.com/board/lists?id=<id>`) → proven httpx_html config 발급 (list = 모바일 보드
페이지, 본문 = desktop view). action path `/board/lists`·`/board/view` 제외 (negative look-ahead),
미니갤은 mgallery 인식기 우선 (충돌 X). 정식갤 전체가 `/preview`·`/watch` 만으로 즉시 등록.

config 출처 = N100 재시도에서 rc=0 받은 stock 생성 config (`tbody.listwrap2 > tr.ub-content.us-post`,
post_id `:self` data-no, robots Crawl-Delay 30 → polite_sleep 30/35).

fixture `tests/recognizers/test_dcinside_main.py` 8 cases (4 보드 인식+schema, desktop, mgallery
미가로채기, action path 제외).

## 회귀 검증

live fetch_list (stock) = 10 posts (post_id/title/date 추출 OK). mgallery (chokaguyahime) 여전히
DCInsideMGalleryAdapter 로 매칭 확인. probe_smoke stage 3 50/50, stage 5 0 FAIL.
