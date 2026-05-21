---
slug: host_platform-openai_docs_c642ce68
url: https://platform.openai.com/docs/changelog
status: 🔧 손 config (httpx_html) — OpenAI docs changelog row selector/post_id 수동 고정
outcome: handcrafted
date: 2026-05-21
failure_keys: [post_id_unique, static_docs_changelog, cloudflare_challenge_static_header_replay, body_empty_acceptable]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [openai, platform-docs, changelog, static-docs, cloudflare, body-empty-acceptable]
requested_by: unknown
---

## 무엇이 일어났나

대상 URL:

```
https://platform.openai.com/docs/changelog
```

사용자 제공 실패 요약은 `httpx_html` 생성 config가 `post_id_unique`에서 4회 실패했다는 것.
마지막 생성 시도는 `list_path='div._ChangelogPage_f3xd6_1 > div.mb-12 > div.mt-5'` 형태로
React-rendered changelog DOM을 잘못 해석했고, post_id가 entry별로 unique하지 않았다.

로컬 preflight:

- recognizer 매칭 없음
- `configs/host_platform-openai_docs_c642ce68.json` 없음
- 기존 `output/poll_state/...FAILED.json` / `output/probe/...` artifact 없음
- 새 `python scripts/probe.py "https://platform.openai.com/docs/changelog"` 실행

새 probe 결과:

```
Verdict: 캡처 헤더 주입 시 정적 가능
권장 진입: httpx + 캡처된 메인 문서 헤더 (S1.Hcap)
글 목록 후보: HTML 15건, JSON API 0건, hydration 0건
```

기본 static GET은 Cloudflare challenge 403이지만, Playwright가 캡처한 docs 요청 헤더를 주입한
`S1.Hcap`은 200 OK였다. robots.txt는 `/docs/changelog`를 disallow하지 않고 `crawl_delay=None`.

## 원인

페이지는 SPA처럼 보이지만 changelog entry 자체는 렌더된 정적 HTML에 있다.

실제 반복 행:

```
main div.mb-12 div.mt-5
```

각 row는 날짜 badge, category badge, markdown paragraph로 구성된다. 별도 per-entry permalink나
article page가 없고, 첫 anchor는 관련 docs 링크일 뿐이다. 따라서 post_id를 anchor만으로 잡으면
중복될 수 있고, 날짜/category만 잡아도 같은 날 여러 entry에서 중복된다.

## 픽스

수동 config:

```
configs/host_platform-openai_docs_c642ce68.json
```

핵심:

- `strategy: "httpx_html"`
- probe의 `list.captured_headers.json`에 있던 docs 요청 헤더를 config headers로 반영
- row selector는 changelog entry인 `main div.mb-12 div.mt-5`
- `post_id`는 `date badge + first paragraph`를 collapse/lower/space-to-dash 후 stable-id regex로 자른 값
- `title`은 first paragraph 텍스트
- `url`은 row의 첫 관련 docs 링크, 없으면 changelog URL
- `summary`는 row markdown HTML
- `article.body_empty_acceptable: true`

이 changelog는 entry row 자체가 게시물 본문 역할이고 별도 article URL이 없다. 그래서 봇 알림은 제목/URL 중심으로
동작하게 두고, baseline 경고(`본문 추출 안 됨`)는 의도된 상태로 둔다.

## 트랙 B 검토

- **2a (인식기)**: X. OpenAI docs changelog 단일 URL 전용 config라 플랫폼 recognizer 가치가 낮다.
- **2b (`--article-url`)**: X. 첫 링크는 관련 docs 링크이고 changelog entry permalink가 아니라 article-url 교정으로 해결되지 않는다.
- **2c/2d (probe 개선)**: X. probe는 이미 올바른 반복 row 후보와 `S1.Hcap` 전략을 노출했다. 실패는 LLM이 `post_id` 조합을 잘못 고른 문제다.
- **A/B (prompt/few-shot)**: 보류. `post_id_unique` 누적은 있으나 원인이 carousel/news root/docs changelog 등으로 섞여 있다. 이번 케이스는 config만으로 해결했고, prompt에는 이미 `post_id` 안정성 및 carousel 중복 주의가 있다.

일반화 안 되는 이유: "per-entry URL 없는 static docs changelog에서 날짜+본문을 post_id로 조합"은 유효하지만,
사이트별 DOM과 permalink 유무 차이가 커서 이번 단건으로 prompt/schema를 넓히면 오히려 잘못된 긴 text-id를 장려할 수 있다.

## robots / polite_sleep

`robots.txt` 200, `crawl_delay=None`, `/docs/changelog` disallow 없음.
config는 probe 권장 `5초+`에 맞춰 `polite_sleep: 5-8s`를 둔다. 일 1회, 목록 1페이지 호출이라
`docs/크롤링 지침.md`의 호출 최소화/간격 원칙에 맞는다.

## 회귀 검증

- `python -c "from engine.recognizers import recognize; print(recognize(URL))"` → `None`
- `python scripts/probe.py "https://platform.openai.com/docs/changelog"` → `S1.Hcap 200 OK`, HTML 반복 후보 15건
- config schema 검증 → `OK`
- `make_adapter` 스모크 → list 30건, unique post_id, 첫 글 body 0자
- `validate_built_config(fetch_articles=1)` → `ok True`, 30건, `article.body_empty_acceptable=true`로 본문 0자 허용
- `python scripts/register.py --config configs/host_platform-openai_docs_c642ce68.json` → baseline 30건 등록

샘플:

```
may-19-released-secure-mcp-tunnel-for-enterprise-customers...  Released Secure MCP Tunnel for enterprise customers...
may-12-deprecated-dall-e-model-snapshots-and-the-realtime-api-beta.  Deprecated DALL·E model snapshots and the Realtime API Beta.
may-11-added-return_token_budget-for-the-responses-api-web-search-tool...  Added return_token_budget for the Responses API web search tool...
```

## 자가 점검 (§6)

1. **자리**: none (수동 config only).
2. **이전 케이스**: `post_id_unique` 7건, `static_docs_changelog` 계열로 Anthropic docs 사례 있음. 이번은 stateful date carry가 필요 없어 adapter 없이 config로 충분.
3. **누구 깰까**: 0. 새 config 파일 단건이며 engine/prompt/probe 변경 없음.
4. **검증**: 위 회귀 검증 참조.
5. **outcome=handcrafted, fix_layer=none**.
6. **fixture**: skip. 새 strategy/휴리스틱/adapter 없음.
7. **트랙 B 보류 사유**: 위 트랙 B 검토 참조.
