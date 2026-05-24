---
slug: host_imf-org_en_cf2cb594
url: https://www.imf.org/en/News
status: ✅ 수동 config (playwright_html, IMF Latest News 8건 baseline)
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [article_body_len]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [imf, nextjs, sitecore, cloudflare-protected, captured-headers, article-body-selector]
requested_by: batch
---

## 무엇이 일어났나

`/en/News` 자동 등록은 목록 추출까지 성공했지만 첫 글 본문 검증에서 실패했다.

```
[FAIL] article_body_len: post_id=pr26168-hong-kong-sar-imf-executive-board-concludes-2026-article-iv-consultation-discussions 0자 (<100 — content selector 의심)
```

probe verdict 는 `CLOUDFLARE_PROTECTED_SITE / 캡처 헤더 주입 시 정적 가능` 이었다. 기본 httpx 헤더는 Akamai 403을 받는다. 브라우저형 헤더로 목록 HTML은 받을 수 있지만, 기사 본문은 hydration 후에야 본문 div가 들어와 `playwright_html`이 필요했다.

## 원인

자동 생성 config는 목록을 `div.link-list--news li`로 정상 추출했다. 실패 지점은 article body selector였다.

자동 생성 selector:

```json
{"selector": "article[aria-label='primary content'] div.ck-content"}
```

실제 렌더 HTML에는 `article[aria-label='primary content']`와 `div.ck-content`가 없었다. 정적 HTML에서는 본문 자리에 loading placeholder가 있고, Playwright hydration 이후 본문이 `article section > div:nth-of-type(2)`로 들어온다. 같은 section 안에는 제목 `h2.pr`, 날짜 `p.date`, 연락처 블록 `.imf-com`이 별도로 있다.

## 픽스

`configs/host_imf-org_en_cf2cb594.json` 수동 config를 추가했다.

- `strategy`: `playwright_html`
- `list.row_selector`: `div.link-list--news li`
- `article.content`: `article section > div:nth-of-type(2)`
- `article.wait_selector`: `article section > div:nth-of-type(3)` (본문 div가 삽입되어 연락처 div가 세 번째 div가 될 때까지 대기)
- headers: probe가 캡처한 브라우저형 request headers 사용
- `polite_sleep`: diagnosis 권장 5초 이상 반영

## 트랙 B 검토

- 2a recognizer: 보류. IMF 전용 뉴스 패턴 하나이며, 같은 플랫폼 범용 recognizer로 확장할 근거가 부족하다.
- 2b first_article_url: 해당 없음. probe의 첫 글 URL은 실제 최신 기사였다.
- 2c probe 휴리스틱: 보류. `article_body_len` 누적은 많지만 이번 실패는 새 구조 신호 누락이 아니라 IMF article DOM의 사이트별 body root 선택 문제다.
- 2d probe 오작동: 해당 없음. Playwright article.html에는 실제 본문이 있었고 정적 HTML에는 hydration placeholder만 있었다.

일반화 안 되는 이유: `article section > div:nth-of-type(2)`는 IMF Sitecore article 템플릿에 특화된 selector라 공용 heuristic/prompt 규칙으로 올리기 어렵다.

## 회귀 검증

- 대상 slug schema validation: PASS
- 대상 `make_adapter` fetch_list/fetch_article: PASS, 목록 8건 및 첫 글 본문 29k자대 확인
- `register.py --config configs/host_imf-org_en_cf2cb594.json`: PASS, 로컬 poll_state 등록 확인
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS

## 참고

`docs/config 자동생성 실패 케이스.md` 매칭: §2b(i) `article_body_len` — 목록은 OK, 본문 selector가 틀린 경우.
