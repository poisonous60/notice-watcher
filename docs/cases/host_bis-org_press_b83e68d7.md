---
slug: host_bis-org_press_b83e68d7
url: https://www.bis.org/press/index.htm
status: 🧩 수동 config — BIS press releases RSS feed로 baseline 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, nav_menu_false_candidate, document_list_js_render]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [bis, rss, press, static-http]
requested_by: batch
---

## 무엇이 일어났나

preflight: miss — host_bis-org_press_b83e68d7.

`https://www.bis.org/press/index.htm` 는 canonical 이 `/press/pressrels.htm` 로 잡히고, 본문에는
`DocumentList` React props 만 있다. 실제 목록 컨테이너는 `data-list-path="all_pressrels"` 를 가진
JS 렌더 영역이며 정적 HTML 의 `.list` 는 wait-stage 상태다.

자동 생성은 probe 의 반복 후보 `ul.localmenu > li.sibling` 를 글 목록으로 오인했다. 이 후보는
`/press/overview.htm?m=254` 같은 local navigation 링크라서 `posts_nonempty: 0건` 으로 실패했다.

## 픽스

BIS 가 공개하는 RSS index 에서 같은 press release 목록의 feed 를 확인했다.

- RSS 안내 페이지: `https://www.bis.org/rss/index.htm`
- press releases feed: `https://www.bis.org/doclist/all_pressrels.rss`

`configs/host_bis-org_press_b83e68d7.json` 은 이 RSS feed 를 `httpx_html` 로 읽는다.

- `row_selector: item`
- `post_id`: `https://www.bis.org/press/<id>.htm` 의 `<id>`
- `title/url/published_at/summary/author`: RSS item 필드
- article 본문: 글 페이지의 `div#cmsContent` fallback `div.document_container`, `div#center`

## 회귀 검증

- recognizer preflight: `recognize('https://www.bis.org/press/index.htm')` -> `None`
- preflight 영향 변경 검사: FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건, uncommitted 변경 0건
- live RSS 확인: `/doclist/all_pressrels.rss` 200, `<item>` 행과 최신 press release 링크 존재
- schema validation: `OK`
- make_adapter smoke: `fetch_list()` 5건, 첫 3개 article body length `p260520=6440`, `p260512=3159`, `p260506=3705`
- `python scripts/register.py --config configs/host_bis-org_press_b83e68d7.json` -> PASS, baseline 25건

## 트랙 B 검토

- **2a (플랫폼 config) — X.** BIS 전용 React `DocumentList`와 `/api/document_lists/<list>.json` 구조다. 기존 recognizer에 맞는 공통 플랫폼은 없다.
- **2b (`--article-url`) — X.** 실패 원인은 첫 글 본문 URL 부족이 아니라 목록 후보가 local menu로 잘못 잡힌 것이다.
- **2c/2d (probe/prompt/engine) — 보류.** `data-list-path` 기반 generic API는 현재 dict map을 반환하고 `httpx_json` 은 list 배열만 처리한다. 단건에서 engine 어휘를 늘리지 않고 공개 RSS로 해결했다.
- **2e (수동 config) — O.** 같은 press releases 목록을 RSS로 안정적으로 노출한다.

일반화 안 되는 이유: 이 변경은 BIS press releases 전용 공개 RSS feed를 선택한 단일 host config다. 새 probe heuristic, prompt rule, recognizer 없이 해결했다.
