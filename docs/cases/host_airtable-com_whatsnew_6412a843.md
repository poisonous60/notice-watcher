---
slug: host_airtable-com_whatsnew_6412a843
url: https://www.airtable.com/whatsnew
status: 🧩 손어댑터 — /whatsnew 빈 마케팅 셸 대신 Newsroom page-data 를 최신순으로 읽어 baseline 30건 등록
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, wrong_first_article_url, marketing_shell_no_rows, next_page_data_reordered]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/airtable_newsroom.py]
engine_files_touched: []
tags: [airtable, whatsnew, newsroom, next-data, handwritten-adapter]
requested_by: unknown
---

## 무엇이 일어났나

대상 URL:

```
https://www.airtable.com/whatsnew
```

초기 로컬 worktree에는 사용자가 언급한 `output/poll_state/host_airtable-com_whatsnew_6412a843.FAILED.json`와
`output/probe/host_airtable-com_whatsnew_6412a843/`가 없었다. preflight 결과:

- `configs/host_airtable-com_whatsnew_6412a843.json` 없음
- recognizer 매칭 없음
- 기존 artifact 없음
- full `register.py "https://www.airtable.com/whatsnew"` 재실행

재현은 Gemini API key 0개라 생성 단계에서 `gemini_api`로 멈췄지만, probe 구조는 원 실패와 같은 방향을 보였다.

`diagnosis.json` verdict:

```
정적 HTTP로 충분
```

`list_candidates.json` 핵심 신호:

- HTML 후보 15건, JSON API 후보 0건, hydration 후보 0건
- `first_article_url=https://www.airtable.com/templates/project-management/expnPwND0WA2x7nhJ`
- 반복 후보 상위가 nav/footer/template 링크이며 실제 update row 가 아님

headless 렌더 후 스크롤/대기까지 확인해도 `/whatsnew` 본문은 hero/nav/footer와 cookie banner뿐이었다. 실제 update/news 카드 목록은 공개
`https://www.airtable.com/newsroom`의 `__NEXT_DATA__.props.pageProps.tiledViewData`에 있었다.

## 원인

`/whatsnew`는 현재 “What's New” 목적의 랜딩/마케팅 셸이지만, 게시글 목록 자체는 노출하지 않는다. 그래서 자동 생성이 `/templates/...` 링크를 첫 글로 오인하고 selector/root를 잡으면 `posts_nonempty` 또는 selector 계열 실패로 흐른다.

단순 `httpx_html` config로 `/newsroom` 카드를 긁는 방식도 한계가 있었다. 렌더 HTML은 featured 카드와 grouped/mobile 카드가 중복되고, 페이지 상단 featured 카드가 실제 최신 항목보다 먼저 나온다. 폴링은 newest-first가 중요하므로 HTML 순서 그대로 쓰면 baseline 선두가 `2025-10-13` 항목이 된다.

## 해결

`AirtableNewsroomAdapter`를 추가했다.

- 목록은 `https://www.airtable.com/newsroom`의 `script#__NEXT_DATA__`를 파싱한다.
- `props.pageProps.tiledViewData`를 사용한다. `featuredNewsData`는 fallback으로만 둔다.
- `cardLink`, `cardTitle`, `cardTopic`, `articlesCount`, `heroImage`를 각각 URL/title/date/category/cover로 매핑한다.
- `cardTopic`은 `%b %d, %Y` 또는 `%B %d, %Y`로 파싱해 UTC 자정 ISO로 저장한다.
- 반환 전 `published_at` 기준 최신순 정렬을 강제한다.
- 본문은 각 newsroom article HTML의 `section[class*='richTextSection']`를 가져오고, 없으면 `main`으로 fallback 한다.

config:

```
configs/host_airtable-com_whatsnew_6412a843.json
```

strategy:

```
handwritten / AirtableNewsroomAdapter
```

## robots / polite_sleep

probe에서 `robots.txt`는 200이고 `crawl_delay=None`이었다. adapter는 probe 권장 5초+에 맞춰 `polite_sleep` 5-8초를 사용한다.

## 회귀 검증

- `python scripts/register.py --config configs/host_airtable-com_whatsnew_6412a843.json` → baseline 30건
- 선두 3건:

```
introducing-superagent  2026-01-27T00:00:00+00:00  Introducing Superagent: The Multi-Agent System That Delivers
chatgpt  2025-12-15T00:00:00+00:00  Introducing Airtable for ChatGPT
deepsky-acquisition-new-cto  2025-10-13T00:00:00+00:00  Airtable announces David Azose as CTO and the acquisition of
```

## 일반화 검토

- 2a platform recognizer: X. Airtable 단일 사이트 전용 구조이며, `/whatsnew` URL을 일반 플랫폼으로 확장할 근거가 없다.
- 2b `--article-url`: X. 첫 글 URL 오인은 맞지만, 문제는 `/whatsnew`에 update row 자체가 없는 것이다.
- 2c probe heuristic: 보류. `__NEXT_DATA__` 안 list 후보 승격은 누적 trigger가 있지만, 이 케이스의 실제 해결은 `/whatsnew`가 아닌 `/newsroom` page-data를 택하는 사이트별 의미 해석이다.
- 2d probe bug: X. probe는 접근성 자체는 맞게 판정했다. 콘텐츠 소스 선택이 사이트별이다.
- 2e handwritten adapter: O. Newsroom page-data를 최신순으로 정렬해야 해서 작은 adapter가 가장 단순하다.

일반화 안 되는 이유: `/whatsnew`와 `/newsroom`의 관계, `tiledViewData` 필드명, featured/tiled 중 어느 배열을 최신 목록으로 볼지는 Airtable 사이트별 지식이다. generic solver에 박기보다 이번 adapter로 제한한다.

## 자가 점검 (§6)

1. **자리**: F (새 handwritten adapter + config).
2. **이전 케이스**: `posts_nonempty`와 `first_article_url` 계열은 누적 trigger가 있지만, 이번 root-cause는 Airtable 전용 `/whatsnew` 셸과 `/newsroom` page-data 관계다.
3. **누구 깰까**: 새 adapter는 `configs/host_airtable-com_whatsnew_6412a843.json`에서만 참조되므로 기존 config 영향 0.
4. **검증**: register baseline 30건 OK, 최신순 선두 확인.
5. **outcome=handcrafted**: 단일 사이트 전용 dedicated adapter라 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy가 아니라 새 adapter라 `probe_smoke.py` stage 3 make_adapter 검증으로 충분.
7. **트랙 B 0건 사유**: 위 §일반화 검토 참조.
