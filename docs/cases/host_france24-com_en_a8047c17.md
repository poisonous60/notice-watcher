---
slug: host_france24-com_en_a8047c17
url: https://www.france24.com/en/
status: ✅ 등록 완료 (preflight b-hit; reuse-probe 자동 생성 playwright_html config)
outcome: improved
date: 2026-05-22
fix_layer: none
failure_keys: [fetch_list, post_id_unique]
config_strategy: playwright_html
tags: [france24, anti-bot, http-403, capability-blocked, batch-2026-05-21-blogcms-gen3]
---

## 원인

`httpx_html` config 시도는 `HTTPStatusError: 403 Forbidden`으로 실패했다. Probe digest는 정적 GET 403, Playwright(S4) list/article 200을 기록했고 `JS 실행 필요 (Cloudflare 등)`으로 판정했다.

이전 자동 시도는 `playwright_html`의 `main [data-article-list]` 방향까지 갔지만 `post_id_unique` 중복 1건으로 실패했고, 마지막 시도는 `aside.o-aside-content--top-articles` 기반 `httpx_html`로 돌아가 403에 막혔다.

## 처리

- preflight: `b-hit` — 실패 시각 이후 영향 영역 커밋 존재. 특히 `75bf56b [fix-layer: F] blogcms gen_fail GEN-3 — medium RSS recognizer + tailscale + france24`가 이 slug의 기존 case를 남겼다.
- `python scripts/register.py --reuse-probe "https://www.france24.com/en/"` 재실행.
- 자동 생성 config가 `strategy=playwright_html`, `row_selector=main [data-article-list]`, `row_required_selector=a[data-article-item-link][href^='/en/']`로 통과했다.
- `post_id`는 `/en/<category>/<date>-<slug>`에서 board prefix를 제거해 추출한다.
- `article.url_template=https://www.france24.com/{board}/{post_id}`로 본문 페이지를 fetch하고, `div.t-content__body` 계열에서 본문을 추출한다.

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://www.france24.com/en/"` → PASS, baseline 30건.
- `configs/host_france24-com_en_a8047c17.json` schema 검증 통과.
- robots: `User-agent: *`의 `Disallow:`는 비어 있고, probe가 `Crawl-delay=5`를 감지했다. config는 `polite_sleep: {min: 5, max: 5}`로 반영했다. robots에는 AI/일반 봇별 `Disallow: /` 항목도 다수 있어 register가 경고를 반복하지만, 이 프로젝트 정책은 robots `Disallow`를 block이 아니라 warn-and-proceed로 처리한다.
- 영향 0개: 새 engine/recognizer 변경 없이 단일 config만 추가했다.

## 트랙 B

일반화 추가 없음. 이번 성공은 기존 probe artifact와 생성기 재시도로 회복된 preflight b-hit 케이스다. France24의 핵심 차이는 정적 GET 403과 Playwright HTML 필요성인데, 이미 probe digest가 이 신호를 제공하고 있었고 새 selector/engine 휴리스틱은 필요하지 않았다.
