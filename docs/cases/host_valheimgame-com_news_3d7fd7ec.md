---
slug: host_valheimgame-com_news_3d7fd7ec
url: https://www.valheimgame.com/news/
status: ✅ 수동 config 등록 (playwright_html, baseline 9건)
outcome: handcrafted
date: 2026-05-26
requested_by: hand-config
failure_keys: [posts_nonempty, js_rendered_list, static_list_missing]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [valheim, nuxt, game-news, playwright-html]
---

## 무엇이 일어났나

preflight: miss — 기존 `configs/host_valheimgame-com_news_3d7fd7ec.json` 없음, recognizer 매칭 없음.
로컬에는 `output/poll_state/host_valheimgame-com_news_3d7fd7ec.FAILED.json` 과
`output/probe/host_valheimgame-com_news_3d7fd7ec/` 가 없어 실패 시각 기준 stale 검사는 할 수 없었다.
N100 probe artifact pull 은 이번 작업 범위에서 제외하고, dev box 에서 URL 을 직접 재확인했다.

정적 GET 은 200 OK 이지만 목록의 반복 row 는 없다. 렌더된 DOM 에서만 `article.news-article-card`
9건이 생기고, 첫 글은 `https://www.valheimgame.com/news/word-from-the-devs-yeah-that-s-a-drawbridge` 다.
글 상세 페이지 본문은 `div.text-content.standard-content.news-article` 로 안정적으로 잡힌다.

## 무엇을 바꿨나

단일 사이트 수동 config 를 추가했다.

- `configs/host_valheimgame-com_news_3d7fd7ec.json`
- strategy: `playwright_html`
- list: `https://www.valheimgame.com/news/`
- wait/row selector: `article.news-article-card a[href*='/news/']` / `article.news-article-card`
- post_id: `/news/{slug}` 의 `{slug}`
- article: `div.text-content.standard-content.news-article`
- `headless` 는 설정하지 않아 N100 기본값 `true` 를 사용한다.

`https://www.valheimgame.com/robots.txt` 는 404 를 반환해 명시적 `Crawl-Delay` 는 없었다.
기본보다 느린 `polite_sleep: 5-7s` 를 넣었다.

## 회귀 검증

- 브라우저 렌더 손 확인:
  - `article.news-article-card` 9건
  - 첫 글 `word-from-the-devs-yeah-that-s-a-drawbridge`
  - 첫 글 본문 selector `div.text-content.standard-content.news-article` 존재
- inline adapter smoke:
  - 목록 9건
  - 첫 글 본문 HTML 2876자
- `python scripts/register.py --config "configs/host_valheimgame-com_news_3d7fd7ec.json"` PASS
  - baseline 9건
  - 최신 글 날짜 `2026-04-28T00:00:00+00:00`
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS
  - stage 3: `257 / 257 OK`
  - stage 5: `108 파일 · 1235 케이스 · 0 FAIL · coverage 44/44`

## 일반화 후보

- **패턴**: 정적 HTML 은 shell/불완전 목록이고, headless 렌더 후 같은 페이지에 카드형 게시글 row 가 생기는 SPA/Nuxt류 뉴스 목록.
- **근거**: `cases_index.py query --signal "Nuxt|SPA|static.*HTML|playwright_html|JS.*render|headless" --json`
  결과는 169건으로 이미 누적되어 있다. 기존 infra case 에서 `playwright_html + wait_selector` 트랙이 자리잡은 유형이다.
- **fix layer 후보**: none — 이번 건은 기존 engine 어휘(`playwright_html`, `wait_selector`, `row_required_selector`)로 풀렸고 새 C/B/A/F 개선은 필요하지 않았다.
- **별도 chunk 필요?** no — ALLOW-LIST 밖 공통 엔진 변경 없이 단일 config 로 해결됐다.

## 트랙 B 검토

- 2a 인식기: X — Valheim 단일 사이트의 Nuxt news DOM 이고 플랫폼 범용 recognizer 근거가 없다.
- 2b first_article_url 교정: X — 실제 첫 글 URL 은 렌더 후 명확하지만, 실패 원인은 article URL 이 아니라 정적 목록 row 부재다.
- 2c/2d probe/schema/prompt: X — 이미 기존 probe/prompt 어휘가 요구하는 해법은 `playwright_html + row-scoped wait_selector` 다.
- 2e 수동 config: 적용 — 렌더 DOM selector 로 목록과 본문을 안정 추출한다.

일반화 안 되는 이유: `article.news-article-card` 와 Storyblok/Nuxt 렌더 구조는 Valheim 사이트 구현 세부사항이다.
같은 host family 나 같은 CMS signature 가 2건 이상 별도로 누적되면 recognizer 후보로 다시 본다.

