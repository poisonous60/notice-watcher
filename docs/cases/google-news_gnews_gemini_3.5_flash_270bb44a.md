---
slug: google-news_gnews_gemini_3.5_flash_270bb44a
url: https://www.google.com/search?q=gemini+3.5+flash&tbm=nws
status: ✅ 플랫폼 config 등록 (Google 검색 → News RSS recognizer + adapter — 모든 검색어 자동 처리)
outcome: handcrafted
date: 2026-05-20
fix_layer: F
failure_keys: [google_serp_not_board, serp_volatile_token_slug_drift]
config_strategy: handwritten
adapters_changed: [GoogleNewsRssAdapter]
engine_files_touched: [engine/recognizers/google_news.py, adapters/google_news_rss.py, adapters/__init__.py, engine/slug.py]
tags: [recognizer, google, news, rss, platform-generalization]
requested_by: poisonous60 (dev, link only)
---

## 무엇이 일어났나

사용자가 Google 뉴스 탭 검색 URL 등록 요청:

> https://www.google.com/search?...&q=gemini+3.5+flash&tbm=nws&...

register 거부:

> 게시판 형식이 아닌 것 같다 — probe 가 같은 호스트로 가는 반복되는 글 링크/목록 API/피드를
> 하나도 못 찾았다. [신호: traffic_json=0 inline_js=0 hydration=0 feed=0 html_same_host=0
> clicked_blocked_by_antibot=https://www.google.com/sorry/index?...]

거부 자체는 정상 — Google SERP 는 게시판 X, anti-bot(`/sorry/`) 챌린지, URL 휘발 토큰.

## 왜 단일 config(§2e) 가 아니라 플랫폼 config 인가

> 어휘: **단일 config** = config 파일 1개, 그 URL 만 (`outcome: handcrafted`).
> **플랫폼 config** = 발급 recognizer 가 플랫폼 전체 자동 처리 — 손-adapter 동반. 자동이 못 푼 걸 박은 수동 config 라 `outcome: handcrafted` (단일 config 보다 scope 만 넓을 뿐 AUTO path 진보 X). ADR 0005 / CONTEXT.md 참조.

Google 검색은 *플랫폼* — 검색어만 바뀌는 같은 패턴이 무한히 들어옴. 단일 config 1개로 끝낼 케이스 X.
또 SERP 직접 크롤은 영원히 불가(ToS·anti-bot·휘발 토큰)지만, Google 이 **공식 News RSS endpoint**
를 노출:

```
https://news.google.com/rss/search?q=<query>&hl=ko&gl=KR&ceid=KR:ko
```

같은 검색어를 여러 언론사 교차 집계로 합법·안정 제공 (Feedly·Inoreader 의 "google search" 구독과
동일 원리). 30건 baseline 출처: blog.google·AI타임스·뉴시스·뉴데일리 경제·미디어펜 등 — 단일
사이트 X, 키워드 검색 결과.

## 픽스 (fix_layer: F — recognizer + adapter + slug 정체성)

### 1. recognizer `engine/recognizers/google_news.py` (신규)
- `//(www.)?google.<tld>/search` + `//news.google.com/(rss/)?search` 매칭
- `q` 추출 → handwritten config (adapter=GoogleNewsRssAdapter). `q` 없으면 None → 폴백
- 로케일: URL 의 hl/gl/ceid 그대로, 없으면 ko/KR/KR:ko. ceid 없고 hl·gl 있으면 `<gl>:<hl>` 합성

### 2. adapter `adapters/google_news_rss.py` (신규)
- News RSS endpoint fetch → `<item>` 파싱. title/link/pubDate/source/description
- post_id = `sha1(guid)` — guid 토큰이 300자+ 라 `generate/validate.py:_STABLE_ID_RE` 의 200자
  cap 초과 → 해시로 축소 (안정·유니크 유지, 원본은 raw._guid 보존). **초기 등록 실패 원인이었고 픽스함**
- 본문: description 스니펫 inline. `<link>` 는 Google consent redirect 라 안 따라감

### 3. slug 정체성 `engine/slug.py:canonical_url` (host-gated 추가)
- SERP URL 의 휘발 토큰(sca_esv/sxsrf/ved/...)이 매번 달라 같은 검색어라도 slug hash 갈림 → 중복 등록
- google search host + `/search` path 일 때만 의미 키(q/hl/gl/ceid/tbm)만 유지, 나머지 drop
- host-gated 라 cross-site 무영향 (arca category 변형 등 회귀 확인)

## 검증

- recognize(user URL) → google-news config 정상
- fetch_list: 30건, 한국 뉴스 5+ 언론사, pubDate ISO
- slug 안정성: 토큰만 다른 두 SERP URL → 동일 slug (`270bb44a`). 다른 검색어 → 분리. arca 회귀 X
- register: ✅ 등록 완료 baseline 30건
- probe_smoke stage 3(50/50)+stage 5(0 FAIL) = exit 0. stage 2 의 skku/trickcal/mabinogi FAIL 은
  pre-existing (fixture 부재, stash 비교로 확정 — 본 변경 무관)

## 트랙 B (일반화) 검토

본 케이스 자체가 트랙 B (recognizer). 추가 일반화 후보:
- probe 휴리스틱화 불필요 — SERP 는 게시판 X 라 probe 신호로 풀 게 없음. recognizer fast-path 가 정답
- 같은 패턴(검색→공식 feed) 다른 엔진(Bing/DuckDuckGo)도 가능하나 요청 시 별도
