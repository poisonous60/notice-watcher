---
slug: host_pubg-com_en_12a87e3e
url: https://www.pubg.com/en/news
status: "✅ 등록 — Vue cookie-banner + scoped-row 캡처/추출 보정 + 수동 config"
outcome: improved
date: 2026-05-26
fix_layer: C
failure_keys: [cookie_modal_click_intercept, vue_scoped_row_miss]
config_strategy: playwright_html
tags: [vue, cookie-banner, games-kr]
---

## 증상

- catalog URL `https://www.pubg.com/news/` 는 locale 없는 shell 로 `rc=3 gate_reject`.
- 실제 게시판은 `https://www.pubg.com/en/news`.
- Phase 9b click probe 는 `/en/news/10106` 글 링크를 골랐지만 cookie modal 이 pointer events 를 가로채 `TimeoutError` 가 났다.
- `list_candidates.json` 은 head 의 `style/meta/link/script` 반복만 상위에 남고 Vue scoped post row 를 못 보여 `first_article_url=None` 이었다.

## 원인

1. `fetch_article_by_click` 이 글 링크 클릭 전에 cookie/consent modal 을 닫지 않았다.
2. PUBG 페이지는 큰 scoped CSS head 때문에 기존 2MB prefix truncate 가 body post DOM 전에 잘렸다. 그 결과 `html_repeating_patterns` 가 실제 `ul.post-contents__body > li.post-contents__card` row 대신 head chrome 반복을 잡았다.
3. Vue scoped attrs(`data-v-*`) 자체는 row data attr 로만 보존하면 되고, selector signature 는 tag+class 기준으로 유지하는 편이 안정적이다.

## 변경

- `probe/fetch_headless.py`
  - Phase 9b 클릭 전 `_dismiss_consent_modals(page)` 를 실행하고 `article_click.json.consent_dismissed` 를 기록.
  - 큰 HTML truncate 시 head prefix 대신 body DOM 을 보존해 SPA/Vue post row 가 probe artifact 에 남도록 함.
  - client-side route 클릭처럼 HAR 에 document 응답이 없지만 body와 final URL 이 있는 경우 status 를 200 으로 보정.
- `probe/extract.py`
  - `head` parent 반복과 `script/style/meta/link` chrome 반복을 `html_repeating_patterns` 후보에서 제외.
- `probe/_contract.py`
  - `article_click.json` 에 optional `consent_dismissed` 필드 추가.
- `configs/host_pubg-com_en_12a87e3e.json`
  - `playwright_html`, `headless` 미지정(default true).
  - list row: `ul.post-contents__body > li.post-contents__card`.
  - article content: `.content-template__inner.fr-view`.

## 검증

- RED: `python scripts/probe_smoke.py --stage 5 --verbose`
  - 예상 실패 5건: missing `_dismiss_consent_modals`, missing `_body_preserving_truncated_html`, missing `consent_dismissed` contract, head chrome/Vue row fixture.
- GREEN: `python scripts/probe_smoke.py --stage 5 --verbose`
  - `106 파일 · 1204 케이스 · 0 FAIL · coverage 44/44`.
- fresh probe: `python scripts/probe.py "https://www.pubg.com/en/news"`
  - `first_article_url=https://www.pubg.com/en/news/10106`
  - `S4.click 200 OK resolved=https://www.pubg.com/en/news/10106`
  - `article_click.json.consent_dismissed=1`
- config 손실행:
  - `list 10`
  - first posts: `10106`, `10110`, `10104`
  - first article body length: `13767`
- register:
  - `python scripts/register.py --config "configs/host_pubg-com_en_12a87e3e.json"`
  - baseline `10건`, state `output/poll_state/host_pubg-com_en_12a87e3e.json`.

## 회귀 검증

- 영향 범위는 probe artifact 생성과 `html_repeating_patterns` 후보 정렬/필터다.
- head/script/style/meta/link 반복은 게시글 row 로 쓰이지 않으므로 제거 영향은 noise 감소다.
- body-preserving truncate 는 기존 cap 을 늘리지 않고, cap 초과 시 body DOM 을 우선 보존한다.
- `playwright_html` config 는 headed mode 를 쓰지 않아 N100 Linux headless 환경의 X server 문제를 만들지 않는다.

## 일반화

- cookie/consent modal click intercept 는 site-specific selector 없이 banner-like ancestor + dismiss text 조합으로 처리했다.
- Vue/Nuxt scoped CSS 가 큰 사이트에서 head chrome 때문에 body row 가 artifact 에 빠지는 문제를 줄인다.
- fix layer: C. probe digest 신호가 실제 row/click 결과를 더 잘 노출하게 하는 변경이다.
