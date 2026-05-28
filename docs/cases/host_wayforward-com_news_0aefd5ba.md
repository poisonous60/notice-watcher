---
slug: host_wayforward-com_news_0aefd5ba
url: https://wayforward.com/news/
status: ✅ Track B 개선 (Tailwind selector grounding + Storyblok all-stories JSON path)
outcome: improved
date: 2026-05-28
fix_layer: F
failure_keys: [selector_syntax, article_body_len]
config_strategy: handwritten
adapters_changed: [StoryblokAllStoriesAdapter]
engine_files_touched: [scripts/register.py, probe/extract.py, probe/_contract.py, scripts/probe.py, engine/recognizers/storyblok.py, adapters/storyblok.py, adapters/__init__.py]
tags: [storyblok, tailwind, selector-grounding, content-json, batch-2026-05-28-games-indie-news-06]
---

## 무엇이 일어났나

`2026-05-28-games-indie-news-06` gen_fail 중 WayForward news.

실패 신호:
- probe digest row selector 가 `div.grid.w-full.relative.gap-6.md:grid-cols-2.xl:grid-cols-3.pt-5 > article.news-card.storyblok__outline` 처럼 Tailwind utility chain 을 그대로 노출.
- agent attempt 1: `[FAIL] article_body_len` — `sigma-star-saga-dx-available-now-...` 본문 0자.
- agent attempt 2: CSS selector pseudo-class syntax + `fetch_list 0건`.
- live 확인: `https://wayforward.com/news/` 200, `article.news-card`/`featured-news-card` rows, `storyblok` signature, `https://wayforward.com/story-data/all-stories.json` 200 JSON. Adapter read-only check: latest 5 posts, first article body 5275 chars.

ship evidence: 사용자 명시 요청 "wayforward 는 글 board (selector 문제). REJECT 말고 이번 batch 안에서 처리" + URL `https://wayforward.com/news/`.

## 원인

두 문제가 겹쳤다.

1. CSS selector grounding: Tailwind responsive class `md:grid-cols-2` 의 `:` 가 CSS pseudo-class 로 해석된다. 이 selector 는 escape 보다 단순화가 맞다. `div.grid > article.news-card` 같은 안정 부모 + row class 로 같은 rows 를 잡는다.
2. content grounding: Storyblok/Nuxt article route 는 정적 article DOM 이 아니라 payload/JSON 에 본문이 있다. HTML content selector 재시도만 반복하면 `article_body_len` 0자로 돌아간다.

## 무엇을 바꿨나

- A-layer: `prompts/config_writer.system.txt` 에 Tailwind utility chain 을 그대로 복사하지 말고 안정 class + child selector 로 줄이라는 규칙 추가.
- D-layer: `prompts/config_writer.retry_skeleton.txt` 와 `scripts/register.py` failure_packet 에 selector syntax 실패 시 `div.grid > article.news-card` 형태의 recovery hint 추가.
- C-layer: `probe.extract.detect_storyblok_platform` + `list_candidates.storyblok_platform` 계약 추가. Storyblok marker 와 news-card signature 를 probe digest 에 싣는다.
- F-layer: `engine/recognizers/storyblok.py` + `StoryblokAllStoriesAdapter` 추가. `/story-data/all-stories.json` 에서 `content.component == newsArticle` 및 board prefix(`news/`)만 읽고, `articleContent` rich text 를 HTML 로 변환한다.
- F-layer register dispatch: Storyblok probe marker 가 있으면 LLM 전 all-stories adapter 등록을 먼저 검증하고, 빈/404/차단이면 일반 파이프라인으로 폴백한다.
- F-layer selector post-processor: LLM/API-loop candidate 의 `list.row_selector` 가 utility-heavy direct-child chain 이면 schema 검증 전 안정 selector 로 줄인다.

## Track B 6-layer audit

- E: miss — schema selector compile gate 는 이미 있음. 이번 실패는 retry/agentic 이 같은 utility chain 을 다시 고르는 문제.
- D: hit — failure_packet 과 retry skeleton 이 selector syntax 실패를 stable selector grounding 으로 안내해야 함.
- C: hit — Storyblok marker 와 all-stories JSON 후보를 probe digest 에 명시해야 content selector 0자 반복을 끊을 수 있음.
- B: miss — few-shot 하나로는 Storyblok body source 와 Tailwind selector syntax를 안정적으로 강제하기 어려움.
- A: hit — config writer system rule 에 "utility chain 복사 금지, 안정 selector로 축약" 지침 필요.
- F: hit — Storyblok all-stories JSON은 재사용 가능한 CMS path. DOM 본문 selector가 아니라 JSON rich text adapter가 맞음.

## 회귀 검증

- `python tests/llm/test_tailwind_selector_postprocess.py` PASS.
- `python tests/probe_heuristics/test_detect_storyblok_platform.py` PASS.
- `python tests/llm/test_register_auto_mode.py` PASS, `failure_packet_tailwind_selector_hint` 포함.
- live read-only adapter check: WayForward all-stories JSON 200, latest posts 5건, first article body 5275 chars.

## 운영 메모

commit/push/N100 deploy 없음. `docs/cases/INDEX.md` 및 `output/cases.sqlite3` backfill 은 사용자 지시대로 이 세션에서 실행하지 않음.
