---
slug: host_yachtclubgames-_root_67bf3b65
url: https://www.yachtclubgames.com/
status: ✅ 수동 config 등록 (httpx_html, baseline 25건)
outcome: handcrafted
date: 2026-05-26
failure_keys: [llm_api]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, blog-cards, root-blog-teasers]
---

## 진단

- preflight: `miss — host_yachtclubgames-_root_67bf3b65`. 작업 시작 시 로컬 `FAILED.json`/probe artifact/config가 없었고 recognizer 매칭도 없었다. N100 ssh/tar pull은 이번 task에서 금지되어 로컬 fresh probe/register로 재현했다.
- last_feedback: `(직전 시도 생성 실패: LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진...)`
- diagnosis verdict: `정적 HTTP로 충분`
- probe digest: HTML 반복 후보 8건, 첫 글 `https://www.yachtclubgames.com/blog/the-art-of-the-game`, JSON API 후보 0건, 본문 진입 OK.
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2e `llm_api`. 사이트 접근/selector 문제가 아니라 현재 dev 환경의 LLM API 키 부재로 자동 config 생성이 중단됐다.
- 분기: 2e 수동 config. root 페이지에 `/blog/<slug>` teaser card가 정적 HTML로 있고 글 본문도 정적 HTML에 있으므로 handwritten adapter나 `playwright_html`은 필요 없다.
- 누적 cross-check: `failure_key=llm_api` count=0, `track_b_trigger=false`. `query --deferred`에는 기존 generic deferred가 다수 있으나 이번 직접 원인은 LLM API 부재다.

## 해결

`configs/host_yachtclubgames-_root_67bf3b65.json`를 추가했다.

- 목록: `article.card.card-post` 중 `a.block[href^='/blog/']`가 있는 row만 채택.
- post_id/url: `/blog/<slug>` href에서 추출.
- 제목/요약/날짜/작성자: card 내부 `h1.title`, `div.intro`, `p.date`.
- 본문: 글 페이지의 `div.article-content-block`.
- enrich: 글 페이지의 `h1.article-title`, `div.article-meta` 날짜/카테고리.

robots/polite_sleep:
- probe에서 `robots.txt`는 404였고 Crawl-Delay는 없었다.
- config에는 기본보다 보수적인 `polite_sleep: {min: 5, max: 6}`를 명시했다.

검증:
- `python scripts/register.py --config configs/host_yachtclubgames-_root_67bf3b65.json` PASS, baseline 25건.
- 첫 3건: `the-art-of-the-game`, `which-weapon-will-you-choose`, `mina-the-hollower-at-pax-east-2026-`.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS: stage 3 config validate/make_adapter 257/257 OK, stage 5 heuristic units 1235 cases 0 FAIL.

## 일반화 후보

- 패턴: root landing page가 marketing/nav 신호를 포함하지만 실제 blog teaser row도 정적으로 제공한다.
- 근거: 이 slug 단건에서만 확인했다. 누적 `llm_api` 사례는 0건이고, 현재 실패는 generic selector 추론 실패가 아니라 LLM 호출 불가다.
- fix layer 후보: 없음. probe/prompt/engine 변경은 이번 allow-list 밖이며, 단건 근거로 root marketing gate를 조정하면 오히려 false-positive 위험이 크다.
- 다음 chunk 필요: no.

## escalate (allow-list 밖 일반화 후보)

없음. site-specific config로 해결했고, engine/probe/prompt 변경이 필요한 반복 패턴은 확인하지 못했다.
