---
slug: host_manga-news-com_index.php_ad12e6cc
url: https://www.manga-news.com/index.php/actus
status: ✅ 수동 config 등록 (httpx_html, public RSS feed)
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty, fetch_list]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [manga-news, rss, cloudflare, feed-remap, list-only-fallback]
---

## 무엇이 일어났나

초기 실패는 `[FAIL] posts_nonempty: 0건`이었다. 실패 이후 probe/engine 변경 커밋
`27ed350`, `5665fa8`가 있어 `register.py --reuse-probe`를 재시도했지만 자동 등록은
회복되지 않았고, 마지막 실패는 `https://www.manga-news.com/rss.xml` 접근 중
`403 Forbidden`으로 바뀌었다.

URL/remap 확인 결과, 요청 URL `https://www.manga-news.com/index.php/actus`는 probe HAR에서
404 에러 페이지(`Erreur - Manga News`)로 캡처됐고 현재 dev box 직접 접근은 Cloudflare
challenge 403을 반환한다. 다만 그 에러 페이지와 정상 article 페이지 모두
`<link rel="alternate" type="application/rss+xml" href="https://www.manga-news.com/index.php/feed/news">`
를 노출하며, 이 feed URL은 dev box에서 HTTP 200으로 열리고 최신 `actus` item을 반환한다.

screen-out: P2에 가까운 원본 URL drift가 있지만, 사이트가 같은 host에서 공개 RSS feed를 명시하고
있어 soft-404 reject 대신 feed remap 수동 config로 처리했다.

robots 확인: `robots.txt` 200, `Disallow: /flarumprivate/`만 존재, `Crawl-delay` 없음.
config에는 기본보다 느린 `polite_sleep` 5~8초를 설정했다.

## 무엇을 바꿨나

`configs/host_manga-news-com_index.php_ad12e6cc.json`을 추가했다.

- `list.url_template`: `https://www.manga-news.com/index.php/feed/news`
- `row_selector`: RSS `item`
- `post_id`: item `link`의 `/index.php/actus/YYYY/MM/DD/...` 경로, fallback은 `guid` md5
- `title`, `url`, `published_at`, `summary`: RSS item에서 추출
- `article.content`: 직접 article page가 열리는 환경에서는 `div.actu-content.bigsize`
- `article.skip_status: [403]`, `body_empty_acceptable: true`: dev box에서는 article direct fetch가 Cloudflare 403이라 RSS 목록/요약만으로 baseline 허용

## 회귀 검증

- config schema validation PASS.
- `make_adapter` 손 실행: list 5건, 첫 글 `2026/05/21/Anime-Dorohedoro-Saison-2-Episode-10-`, body 0 chars, raw `fetch_status=403`.
- `python scripts/register.py --config "configs/host_manga-news-com_index.php_ad12e6cc.json"` PASS: baseline 15건 등록, 본문 미추출 경고.
- `python scripts/probe_smoke.py --stage 3 --json` PASS: 187 / 187 OK.

## 트랙 B 검토

- 2a 인식기: 보류 — Manga News 단일 host의 feed remap이다. 같은 플랫폼 반복 사례 없이 recognizer를 넓히지 않았다.
- 2b first_article_url 교정: X — probe가 첫 글 URL을 못 찾은 이유는 원본 list URL이 에러 shell이기 때문이다.
- 2c/2d probe/schema/prompt: 보류 — `posts_nonempty` 누적 사례와 deferred query는 `track_b_trigger=true`였지만, 이번 codex 위임의 allow-list가 `configs/<slug>.json`과 `docs/cases/<slug>.md`로 제한되어 shared track-B 파일은 편집하지 않았다.
- 2e 수동 config: 적용 — 사이트가 공개 RSS feed를 직접 광고하고 있어 가장 작은 작동 변경이다.

track-B defer: user-scoped same-tree race / shared files forbidden.
