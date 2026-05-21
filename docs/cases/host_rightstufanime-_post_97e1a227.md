---
slug: host_rightstufanime-_post_97e1a227
url: https://www.rightstufanime.com/post
status: 🚫 거부 — Right Stuf legacy URL 이 Crunchyroll Store 홈으로 remap
outcome: rejected
date: 2026-05-22
failure_keys: [probe_timeout, url_remapped, non_board_homepage, nav_only_candidates]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [rightstufanime, crunchyroll-store, url-remap, non-board, rejected]
requested_by: batch
---

## 무엇이 일어났나

batch 실패 당시에는 `probe_timeout` 으로 들어왔다.

`last_feedback`:

- `[FAIL] probe_timeout: probe timeout (120s)`

이후 로컬 `output/probe/host_rightstufanime-_post_97e1a227/` 에 재수집 산출물이 생겼지만, 산출물은
게시판이 아니라 Crunchyroll Store 홈 화면이었다. 제출 URL `https://www.rightstufanime.com/post` 는
현재 `https://store.crunchyroll.com/` 로 302 redirect 된다. 렌더된 HTML 의 canonical 도
`https://store.crunchyroll.com/` 이며, title 은 `Explore the Ultimate Anime & Manga Shop |
Crunchyroll Store` 다.

`list_candidates.json` 의 `first_article_url` 은
`https://www.rightstufanime.com/collections/all-in-stocks/` 로 잡혔다. 이는 게시글이 아니라
Crunchyroll Store 상품 컬렉션 링크다. 후보도 CSS/style, SVG symbol, category/component, footer/login
링크 위주라 notice board 로 볼 수 없다.

## 판정

config 를 만들지 않았다. 제출 URL 이 legacy host 에 남은 게시판 URL 이 아니라, 상점 홈으로 remap 된
orphan URL 이기 때문이다. 이 상태에서 수동 config 를 만들면 상품 컬렉션이나 내비게이션을 게시글로
오수집하게 된다.

screen-out: remap/homepage drift — `rightstufanime.com/post` -> `store.crunchyroll.com/`, canonical
homepage, post row 없음.

## Track B 검토

- **2a 인식기 — X.** 특정 legacy URL 이 다른 host 의 storefront home 으로 remap 된 케이스라 게시판
  recognizer 를 만들 대상이 아니다.
- **2b article-url — X.** 첫 글 URL 오선정 이전에 list URL 자체가 게시판이 아니다.
- **2c/2d probe/prompt/engine — 보류.** `submitted host != canonical host` 이고 canonical 이
  storefront homepage 일 때 screen-out 하는 generic gate 후보는 있다. 다만 이번 위임 지시는
  `prompts/classify.system.txt`, `probe/extract.py`, `scripts/register.py`, `engine/recognizers/*`,
  `engine/*`, `generate/*` 변경을 금지했으므로 Track-B 코드는 손대지 않았다. 별도 직렬 작업에서
  canonical-host drift + homepage remap gate 로 다루는 편이 맞다.
- **2e 수동 config — X.** 수집 가능한 게시판 URL 이 확인되지 않았다.

일반화 안 되는 이유: 이 작업 범위에서는 URL dead/remap 판정 기록만 남기며, shared gate 파일 수정은
same-tree race 방지를 위해 제외했다.

## 회귀 검증

- `preflight: b-hit — host_rightstufanime-_post_97e1a227 [27ed350, 5665fa8]`
  - 기존 `configs/host_rightstufanime-_post_97e1a227.json` 없음.
  - recognizer 매칭 없음.
  - FAILED 이후 probe/engine 영향 커밋 존재.
  - `python scripts/register.py --reuse-probe "https://www.rightstufanime.com/post"` 는 120초 내 종료하지
    못해 자동 회복으로 보지 않았다.
- URL/remap 확인
  - `curl -I -L https://www.rightstufanime.com/post` -> `302 Location: https://store.crunchyroll.com/`
    -> `200 OK`.
- probe artifact 확인
  - `list_candidates.json`: `first_article_url` =
    `https://www.rightstufanime.com/collections/all-in-stocks/`, `traffic_json_api_candidates=[]`,
    `hydration_list_candidates=[]`.
  - `list.html`/`article.html`: canonical `https://store.crunchyroll.com/`, Crunchyroll Store homepage
    title, footer/store/category links.
- robots 확인
  - `robots.json`: status 200, disallow 없음, crawl_delay 없음.

## 자가 점검 (§6)

1. **자리**: none/rejected. config, adapter, engine, probe, prompt 변경 없음.
2. **이전 케이스**: 이번 케이스의 핵심은 `probe_timeout` 자체가 아니라 legacy URL remap 으로 인한
   non-board homepage 다.
3. **누구 깰까**: case 문서 1개만 추가. 기존 config/engine 영향 0.
4. **검증**: redirect/canonical/list 후보/robots 확인. 수집 가능한 게시판 source 없음.
5. **outcome=rejected**: URL 이 게시판이 아니므로 no config.
6. **fixture**: 새 strategy/heuristic 이 아니며, shared Track-B 파일 수정 금지 지시 때문에 fixture 추가 없음.
7. **트랙 B 사유**: 위 §Track B 검토 참조.
