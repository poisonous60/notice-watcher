---
slug: host_mangaupdates-co_news.html_f4a7e1b6
url: https://www.mangaupdates.com/news.html
status: fixed (url remapped to root news rows)
outcome: handcrafted
date: 2026-05-22
failure_keys: [fetch_list, url_dead, remap_root_news]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [batch, manga, url-drift, remap, httpx_html]
requested_by: batch
---

## 무엇이 일어났나

`https://www.mangaupdates.com/news.html` 는 probe 시점에 모든 진입 전략에서 HTTP 404였다.
도메인 루트는 200이었고, 루트 HTML 안에 `news-row-module__pHUmoa__news_container` 뉴스 행 10개와
`/rss` alternate feed가 같이 노출됐다.

## 진단

- last_feedback: `[FAIL] fetch_list` at `https://www.mangaupdates.com/news.html?page=1`
- verdict: `TARGET_NOT_FOUND`
- screen-out: P2 아님. 404 shell이지만 루트에 같은 News content가 살아 있어 soft-404 패턴 추가가 아니라 URL drift/remap 케이스.
- preflight: b-hit — 실패 이후 `27ed350 [fix-layer: C+F] track-B: WordPress REST recognizer + soft-404 감지`가 있었고, 이 케이스는 공유 코드 추가 변경 없이 config로 회수.

## 해결

원 slug를 유지하되 `list.url_template` 은 죽은 `/news.html` 이 아니라 `https://www.mangaupdates.com/`
로 remap했다. 기존 자동 config가 붙인 `?page=1` pagination은 404를 만들기 때문에 `pagination.kind=none`으로
고정했다.

뉴스 행은 루트 HTML에 정적으로 들어 있다:

- row: `div.news-row-module__pHUmoa__news_container`
- id/url: comments 영역의 `/topic/<id>/<slug>` 링크
- title/content/author: 같은 row 내부 news title/content/author block

## 트랙 B

누적 조회에서 `fetch_list`와 `TARGET_NOT_FOUND|404|soft-404|feed_candidates`는 track-B trigger였지만,
이번 failure는 입력 URL drift와 잘못된 pagination의 조합이다. probe는 이미 루트 200, `/rss` feed 후보,
404 verdict를 산출하고 있었고, 실패 이후 soft-404/url-dead 계층 변경도 들어갔다. 같은 패턴에 대한 추가
recognizer나 probe heuristic은 이번 patch에서 보류했다.

## 검증

- artifact parse: 루트 HTML snapshot에서 뉴스 row 10건 확인.
- config local parse: 같은 snapshot에서 post_id/title/url/summary 추출 가능.
- `python scripts/register.py --config configs/host_mangaupdates-co_news.html_f4a7e1b6.json`: PASS, baseline 10건.
- `python scripts/probe_smoke.py --stage 3 --stage 5 --json`: PASS, 82 파일 / 883 cases / 0 FAIL.
