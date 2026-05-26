---
slug: host_annapurnaintera_news_72cf03d0
url: https://www.annapurnainteractive.com/news/
status: ✅ 수동 config 등록 (httpx_html list, internal redirector URLs only)
outcome: handcrafted
date: 2026-05-26
failure_keys: [article_body_len, external_article_redirect]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [annapurna, hand-config, press-links, body-optional]
---

## 무엇이 일어났나

preflight: miss — `configs/host_annapurnaintera_news_72cf03d0.json` 없음, recognizer 매칭 없음, 실패 시점
`2026-05-26T06:15:02Z` 이후 prompts/engine/probe/generate 관련 commit 없음.

probe 는 목록 페이지를 정적 HTTP로 충분하다고 봤고, `ul.pages-list > li.pages__item.border-color` 7건을
후보로 잡았다. 첫 내부 글 URL은
`https://www.annapurnainteractive.com/en/news/interview-i-am-dead-is-an-innovative-puzzle-adventure-about-celebrating-life-while-being-dead`
였다.

자동 생성기는 상세 진입에서 외부 press URL을 따라가거나 `destructoid.com` URL 템플릿을 만들며
`article_body_len`/404로 실패했다. 실제 목록 row는 Annapurna 내부 `/en/news/` redirector URL을
노출하지만, 그 URL 자체가 외부 매체 기사로 302 redirect 하는 구조다.

## 픽스

`configs/host_annapurnaintera_news_72cf03d0.json` 을 추가했다.

- `strategy`: `httpx_html`
- `list.url_template`: `https://www.annapurnainteractive.com/en/news`
- `row_selector`: `ul.pages-list > li.pages__item.border-color`
- `row_required_selector`: `a.reset-link[href^='https://www.annapurnainteractive.com/en/news/']`
- `post_id/title/url/author`: row 내부의 내부 redirector 링크와 표시 텍스트
- `article.content`: 빈 목록 + `body_empty_acceptable: true`

## 검증

- `python scripts/register.py --config "configs/host_annapurnaintera_news_72cf03d0.json"` PASS
  - baseline 7건
  - 최신 샘플: `interview-i-am-dead-is-an-innovative-puzzle-adventure-about-celebrating-life-while-being-dead`
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS

## 트랙 B 검토

- 2a 인식기: X — 사이트 고유 press-link 목록이며 재사용 가능한 플랫폼이 아니다.
- 2b article URL 교정: 부분 해당. 잘못된 외부 URL 생성이 문제였으나, 내부 URL도 본문 페이지가 아니라
  외부 기사로 redirect 하는 redirector다.
- 2c/2d probe/prompt: X — probe 는 이미 내부 첫 글과 row selector 를 올바르게 제시했다.
- 2e 수동 config: 적용.

## 유사 케이스 후보

- 패턴: press-link index with internal redirector URLs
- 신호: 목록 row href 는 same-host `/en/news/<slug>` 이지만 상세 fetch 는 외부 매체로 302 redirect
- fix layer 후보: F (follow_redirects=false 또는 body-fetch skip 어휘)
- 다음 chunk 적합성: no (현재는 단일 사이트 사례, allow-list 밖 엔진 변경 필요)

## escalate (allow-list 밖 공통 개선)

본문 fetch 단계에서 redirector URL의 외부 302를 따라가지 않도록 하는 config 어휘가 없다.
공통 개선을 하려면 `article.follow_redirects: false` 또는 `article.skip_fetch: true` 같은 F-layer 엔진 변경이 필요하다.
이번 작업은 allow-list 안에서 site config만 추가하고, 알림은 제목 + 내부 Annapurna URL 기준으로 동작하게 했다.
