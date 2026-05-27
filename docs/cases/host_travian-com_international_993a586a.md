---
slug: host_travian-com_international_993a586a
url: https://www.travian.com/international/news/
status: "✅ handcrafted: sitemap list + hydrated SPA article body"
outcome: handcrafted
fix_layer: none
failure_keys:
  - agentic_fake_config
  - posts_nonempty_zero
  - spa_shell
  - sitemap_article_urls
config_strategy: playwright_html
requested_by: user (batch ship request)
date: 2026-05-27
adapters_changed: []
engine_files_touched: []
tags: [manual-config, travian, sitemap, spa-hydration]
---

## 무엇이 일어났나

preflight: miss — recognizer 매칭 없음. 이 worktree 에는 기존
`configs/host_travian-com_international_993a586a.json` 과
`output/probe/host_travian-com_international_993a586a/` 가 없었다.

사용자 ship evidence: "Task: ship 2 sites (afkjourney/news + travian/international/news) manual configs" 와
`https://www.travian.com/international/news/` slug 가 직접 지정됐다.

live 확인:
- `https://www.travian.com/international/news/` 는 200 OK 이지만 정적 HTML 은 `#root` SPA shell 이다.
- 기존 agentic 산출물은 `row_selector: "#root"` + `post_id: const "root"` 형태의 fake 1-row config 라고 보고됐다.
- `https://www.travian.com/sitemap.xml` 은 200 OK 이고 `/international/news/YYYY/MM/DD/<slug>/` URL 115건을 노출한다.
- 첫 글 `https://www.travian.com/international/news/2026/05/26/mobile-app-3-12/` 는 Playwright hydration 후
  `div.contentWrapper.newsArticle` 에 본문이 생긴다.

probe artifact: absent in this worktree. 사용자 brief 의 artifact 신호와 live HTTP/sitemap 확인을 근거로 진행했다.

## 픽스

`configs/host_travian-com_international_993a586a.json` 을 추가했다.

- `strategy`: `playwright_html`
- `list.url_template`: `https://www.travian.com/sitemap.xml`
- `row_selector`: `url`
- `post_id`: `loc` 에서 `/international/news/YYYY/MM/DD/slug/` 추출
- `title`: URL slug 를 공백으로 정규화
- `published_at`: URL 날짜를 ISO date 로 변환
- `article.content`: hydrated DOM 의 `div.contentWrapper.newsArticle`

`httpx_html` sitemap list 만으로는 article body 가 정적 shell 에서 비어 있었다. 그래서 list 와 article 을 같은
`playwright_html` strategy 로 맞췄다. `headless: false` 는 넣지 않았다.

## Track B 6-layer audit

- E schema 거부: miss — fake `#root` 1-row 는 문법상 유효한 config 라 schema 만으로는 잡기 어렵다.
- D retry feedback: miss — `posts_nonempty`/`title_nonempty` 류 retry 로도 sitemap source 선택과 SPA article hydration 을 동시에 보장하지 못한다.
- C probe digest 신호: miss — sitemap 후보는 이미 발견된 신호이고, 이번 변경은 새 probe 휴리스틱이 아니라 해당 사이트의 source 선택이다.
- B few-shot: miss — sitemap-only list + hydrated article body 조합은 일반 예제로 박기에는 아직 단일 사이트 근거다.
- A system prompt: miss — 같은 batch 내 2+ 동일 패턴으로 확인된 generic prompt miss 가 아니다.
- F engine code: miss — 새 mixed-strategy engine 이 있으면 더 깔끔하지만 요청 scope 밖이다.

결론: Track B 일반화 후보는 보류하고, 사용자 명시 ship 요청에 따라 Track A 수동 config 로 처리했다.

## 검증

- `python -m scripts.validate_config configs/host_travian-com_international_993a586a.json` PASS
  - `fetch_list`: 30건
  - `article_body_len`: `2026/05/26/mobile-app-3-12` 5684자
- make_adapter direct check PASS
  - list 10건
  - first ids: `2026/05/26/mobile-app-3-12`, `2026/05/21/changelog-467-2`, `2026/05/20/eid-al-adha-truce`
  - first article body 5684 chars
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS
  - stage 3: 284 / 284 OK
  - stage 5: 127 files, 1380 cases, 0 FAIL, 1 WARN (`test_worker_failure_routing` protocol warning)
- `python scripts/vocab_lint.py` PASS

## escalate 후보

- 패턴: sitemap list 는 정적 접근 가능하지만 article 은 SPA hydration 필요.
- 신호: board URL 정적 후보 0, sitemap 에 article URL 다수, article 정적 HTML 은 shell, hydrated DOM 에 본문 존재.
- fix layer 후보: F (list/article strategy 분리 또는 article fetch_kind `playwright_html`)
- 다음 worktree 적합성: yes, 같은 패턴이 2건 이상 쌓이면 generic engine vocabulary 로 검토.
