---
slug: host_amiami-com_eng_f0c7cc0e
url: https://www.amiami.com/eng/news/
status: ✅ 수동 config 등록 (playwright_html, list-only accordion)
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty, post_id_stable_shape, matches_probe_first_article]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [amiami, hand-config, playwright-html, cloudflare, list-only]
---

## 무엇이 일어났나

`https://www.amiami.com/eng/news/` 는 살아 있는 게시판 URL 이다. 정적 접근 일부는 Cloudflare
challenge 를 받지만 Playwright 렌더링은 200 OK 이고, `div.wrapper > div.topics-list` 아래에 날짜,
제목, 본문 요약을 포함한 공지 row 가 노출된다. `robots.txt` 는 200 이며 `Disallow` 와
`Crawl-delay` 가 없다.

초기 실패는 `[FAIL] posts_nonempty: 0건` 이었고, 실패 이후 probe/engine 변경을 반영해
`register.py --reuse-probe` 를 다시 돌리자 목록 추출은 회복됐다. 남은 실패는
`[FAIL] post_id_stable_shape` 였다. 자동 생성 config 가 공지 제목 전체를 post_id 로 사용하면서
공백과 문장부호가 들어가 안정 ID 검증을 통과하지 못했다.

screen-out: P1/P2 해당 없음. 이 페이지는 단일 content page 나 soft-404 shell 이 아니라 렌더된 공지
목록이다.

## 무엇을 바꿨나

`configs/host_amiami-com_eng_f0c7cc0e.json` 을 추가했다.

- `strategy`: `playwright_html`
- `list.url_template`: `https://www.amiami.com/eng/news/`
- `row_selector`: `div.wrapper > div.topics-list > dl.topics-list__list-item`
- `post_id`: 날짜 + 제목 앞 80자, stable-shape 에 맞게 공백/문장부호 정규화
- `title`, `published_at`, `summary`: row 안의 date/title/body span 에서 추출
- `article`: 상세 URL 이 없는 list-only 공지라 `content: []`, `body_empty_acceptable: true`
- `polite_sleep`: probe 권장 5초 이상에 맞춰 5~6초

## 회귀 검증

- config schema validation PASS.
- `make_adapter` 손 실행: list 10건, 첫 글 `Apr-13-2026-Notice-Regarding-Changes-to-DHL-Fuel-Surcharge-Rates`, body 0 chars.
- `python scripts/register.py --config "configs/host_amiami-com_eng_f0c7cc0e.json"` PASS.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.
- 전체 `python scripts/probe_smoke.py` 는 기존 fixture artifact 문제로 stage 1/2 FAIL
  (`skku`/`mabinogi` diagnosis 누락, `trickcal`/`arca` robots.json `sitemaps` 누락). 이번 config 는
  stage 3 에서 검증됐다.

## 트랙 B 검토

- 2a 인식기: X — AmiAmi 단일 호스트의 고유 HTML 구조다. 다른 사이트로 넓힐 플랫폼 신호가 없다.
- 2b first_article_url 교정: X — probe 의 `first_article_url` 은 nav 의 `/eng/ranking/` 오인이지만, 실제
  config 는 같은 URL 안의 list-only row 를 사용하므로 글 URL 교정으로 풀 문제가 아니다.
- 2c/2d probe/schema/prompt: 보류 — 자동 retry 가 이미 올바른 row 를 찾았고, 실패 원인은 이 사이트의
  상세 URL 부재와 post_id 구성이다. user 지시상 shared recognizer/screen-out 변경은 이번 result 에서 제외했다.
- 2e 수동 config: 적용 — 기존 `playwright_html` + list-only 설정으로 충분하다.

일반화 안 되는 이유: 상세 URL 없는 아코디언 공지는 사이트별 DOM 과 제목 운영 방식에 의존한다. 같은
플랫폼 반복 사례가 확인되기 전에는 단일 config 가 가장 작은 변경이다.
