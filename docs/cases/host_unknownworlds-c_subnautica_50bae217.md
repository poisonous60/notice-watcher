---
slug: host_unknownworlds-c_subnautica_50bae217
url: https://unknownworlds.com/subnautica/news/
status: 🔧 손 config (httpx_html) — Unknown Worlds Subnautica SSR cards
outcome: handcrafted
date: 2026-05-28
requested_by: batch
failure_keys: [title_nonempty]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [unknownworlds, subnautica, nextjs-ssr, static-html]
---

## 무엇이 일어났나

`[FAIL] title_nonempty failed; row title extraction empty`.

catalog URL `https://unknownworlds.com/subnautica/news/`는 live에서 `/en/news/news`로 이어진다. 목록 HTML은 Next.js SSR로 내려오며 `div[data-testid^="slide-"]` 카드마다 `/news/<slug>` 링크가 있다. 자동 생성은 이미지 `alt=""`를 title로 잡은 것으로 보이고, 실제 title은 카드 안 heading(`h6`)에 있었다.

preflight: miss — 이미 등록된 config/recognizer 없음. 이 작업은 사용자가 `2026-05-28 games-online-live-service-04` gen_fail 잔여 2건을 Track A 손 config로 즉시 처리하라고 slug와 catalog URL을 명시했다.

screen-out: none — live HTML에 반복 article cards 8건이 있어 content-as-list, soft-404, fake feed가 아니다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)

`configs/host_unknownworlds-c_subnautica_50bae217.json` — `httpx_html`.

- `list.url_template`: `https://unknownworlds.com/en/news/news`
- `row_selector`: `div[data-testid^="slide-"]:has(a[href^="/news/"])`
- `post_id`: `/news/<slug>` href에서 slug 추출
- `title`: 카드 내부 `h1,h2,h3,h4,h5,h6` text
- `url`: `/news/<slug>`를 `https://unknownworlds.com` 기준으로 join
- `published_at`: `ArticleCard_meta` 첫 div의 `MM.DD.YY`를 ISO8601로 변환
- `article.url_template`: `https://unknownworlds.com/en/news/{post_id}`, `body_empty_acceptable: true`

## Track B 6-layer audit

- E schema: miss — config 스키마로 막을 오류가 아니라 selector 선택 문제.
- D retry feedback: miss — validation feedback은 title empty를 이미 전달했고, 사이트별 DOM 위치 문제.
- C probe digest: miss — SSR HTML에 필요한 title/date가 이미 있어 새 probe 신호가 필요하지 않음.
- B few-shot: miss — webpack hash class 대신 stable `data-testid`와 heading을 쓰는 단일 사이트 조합.
- A system prompt: miss — 이미지 alt가 비어 있으면 heading을 보라는 일반 규칙은 이미 상식 수준이고, 이 한 케이스로 prompt 확장 근거 부족.
- F engine: miss — `httpx_html` + soupsieve selector + 기존 transforms로 표현 가능.

## 회귀 검증

- live curl 확인: `https://unknownworlds.com/en/news/news` status 200, `div[data-testid^="slide-"]:has(a[href^="/news/"])` 8건.
- 손 실행: list 3건 샘플에서 title/date/url 정상, 첫 글 body 23134 chars.
- `python scripts/register.py "https://unknownworlds.com/subnautica/news/" --config configs/host_unknownworlds-c_subnautica_50bae217.json` → rc=0, baseline 8건.

## 일반화 안 함 이유

Unknown Worlds 전용 URL/DOM 구조의 수동 selector다. 같은 실패가 2개 이상 누적된 generic 패턴이 아니고, 현재 엔진으로 충분히 표현된다.
