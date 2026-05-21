---
slug: host_box-com_blog_de163a6a
url: https://box.com/blog/category/product-news
status: ⛔ capability_blocked — original URL is Cloudflare-challenged for static fetch and 404 under Playwright; moved Box Blog category is also CF managed-challenge at runtime
outcome: no_change
date: 2026-05-21
fix_layer: none
failure_keys: [capability_blocked, cloudflare_challenge, original_url_404, moved_blog_category, playwright_runtime_blocked]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [capability-blocked, cloudflare, box-blog, moved-url, playwright, product-news]
requested_by: poisonous60
---

## 진단

preflight 결과는 `miss` 였다. 로컬에는 `configs/host_box-com_blog_de163a6a.json` 이 없었고,
`engine.recognizers.recognize("https://box.com/blog/category/product-news")` 도 `None` 이었다.
N100 접근은 금지 조건이라 원격 triage pull 없이 dev box 에서 full probe 를 재실행했다.

원 URL `https://box.com/blog/category/product-news` 재현 결과:

- `S1.H2/H3/H4`: 모두 `403 BLOCKED_BOT`, `cf-mitigated: challenge`,
  `cdn-cgi/challenge-platform`.
- `B2 robots.txt`: `403 BLOCKED_BOT`, `__cf_chl`.
- `S4 Playwright`: `404 NOT_FOUND`, `x-matched-path: /en/404`.
- `S1.Hcap`: captured browser headers 재사용 후에도 `403 BLOCKED_BOT`.
- `list_candidates.json`: 글 후보 0건, `first_article_url: null`.
- register 결과: `capability_blocked (anti-bot/captcha)`.

## 이동 URL 확인

검색 결과와 직접 확인 기준으로 Box Blog 는 현재 `blog.box.com` 아래에서 운영되고, Product 계열
카테고리는 `https://blog.box.com/category/product` 이다. 이 URL은 probe S4 에서 한 차례
200 OK 로 렌더됐고 `main article` 20건 및 `__NEXT_DATA__.props.pageProps.post.posts` 20건이
확인됐다.

하지만 등록 가능한 config 로는 고정하지 않았다.

- runtime `playwright_html` 으로 같은 URL을 fetch 하면 Cloudflare managed challenge HTML만 반환되어
  baseline 0건이었다.
- probe S4 와 runtime strategy 의 브라우저 옵션 차이를 맞추는 실험을 했지만, Chrome UA,
  `AutomationControlled` 비활성화, service worker block, resource block 조합으로도 runtime 은
  여전히 challenge page 였다.
- `https://backend.blog.box.com/api/v1/posts?category=product` 및 backend category URL도
  Cloudflare managed challenge 로 막혔다.
- Jina Reader 경유도 challenge 요약만 반환했다.

따라서 원 URL을 현재 category URL로 보정한 config 파일을 남기면 baseline 0건짜리 오등록이 되므로
config 변경은 폐기했다.

## 결론

이번 케이스는 selector/schema 문제가 아니라 접근 계층 문제다. 원 URL은 현재 Playwright 기준 404이고,
이동된 Box Blog category/API 도 dev box runtime 에서 Cloudflare managed challenge 를 통과하지 못한다.
정책상 금지된 로그인을 요구하는 케이스는 아니지만, 현 자동 경로와 허용된 stealth 수준으로는 terminal
`capability_blocked` 로 보는 게 맞다.

## 트랙 B

`capability_blocked` 누적 cross-check 는 8건으로 `track_b_trigger=true` 이다. 다만 이 케이스에서
즉시 일반화할 코드는 없다. probe S4 가 일시적으로 200을 받은 뒤 runtime 이 challenge 로 막히는
변동성은 `playwright_html` 기본 옵션 한두 개로 해결되지 않았다. 이 문제를 일반화하려면 별도 어휘/능력
확장(`storage_state`, stronger stealth profile, 또는 curl_cffi/TLS impersonation) 설계가 필요하다.

## robots / polite_sleep

등록 config 를 만들지 않았으므로 runtime `polite_sleep` 적용 대상은 없다. 재시도 실험은 1페이지 진입
확인과 backend API 확인으로 제한했고, 반복 polling config 는 남기지 않았다.

## 검증

- `python scripts/register.py "https://box.com/blog/category/product-news"`: rc=1, FAILED marker 복구,
  `capability_blocked`.
- `python scripts/register.py --config configs/host_box-com_blog_de163a6a.json`: 실험 config baseline 0건,
  config 폐기.
- `curl https://backend.blog.box.com/api/v1/posts?category=product`: Cloudflare managed challenge.
- `curl https://r.jina.ai/http://r.jina.ai/http://https://blog.box.com/category/product`: challenge 요약만 반환.
