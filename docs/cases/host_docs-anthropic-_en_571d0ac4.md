---
slug: host_docs-anthropic-_en_571d0ac4
url: https://docs.anthropic.com/en/release-notes/overview
status: ✅ 해결 (Anthropic docs release notes handwritten adapter + slug-stable recognizer)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [meta_diverging_false_positive, post_id_unique, static_docs_changelog]
config_strategy: handwritten
adapters_changed: [adapters/anthropic_docs.py]
engine_files_touched: [engine/recognizers/anthropic_docs.py]
tags: [anthropic-docs, release-notes, changelog, handwritten-adapter, recognizer, slug-stable]
requested_by: unknown
---

## 무엇이 일어났나
대상 URL은 Anthropic docs 릴리즈 노트 overview:

```
https://docs.anthropic.com/en/release-notes/overview
```

로컬 snapshot에는 기존 `output/poll_state/host_docs-anthropic-_en_571d0ac4.FAILED.json`와
`output/probe/host_docs-anthropic-_en_571d0ac4/`가 없었다. preflight 결과:

- configs/ 없음
- recognizer 매칭 없음
- 기존 artifact 없음
- full `register.py "<URL>"` 재실행

재현 결과 현재 코드에서는 예전 `post_id_unique` 실패까지 가지 않고, 앞단 게이트에서 거부됐다.

```
[register] ❌ 등록 거부 — 단일 article (meta 선언 + 발산 first_article).
```

`diagnosis.json` verdict 는 `정적 HTTP로 충분`. `list_candidates.json`의 핵심 신호:

- `article_meta_signals.is_article_page=true` (`og:type=article`)
- `first_article_url=https://docs.anthropic.com/docs/en/agents-and-tools/mcp-tunnels/overview`
- 실제 반복 후보는 `#content-container > h3` 날짜 98개와 그 뒤의 `ul > li` 릴리즈 노트 행

즉 이 페이지는 `og:type=article`을 달고 있지만, 실제로는 날짜별 릴리즈 노트 changelog 목록이다.
probe가 첫 링크를 docs 내부 다른 섹션 문서로 잡으면서 `_meta_article_diverging_check`가 false reject 했다.

## 원인
자동 config로 풀기 어려운 구조였다.

- 각 날짜는 `#content-container > h3`
- 해당 날짜의 릴리즈 노트 행은 바로 뒤 `ul > li`
- 선언적 config의 row 단위 CSS 추출만으로는 preceding `h3` 날짜를 각 `li` row에 안정적으로 carry 하기 어렵다.
- `li` 안 첫 anchor는 관련 문서 링크이지 릴리즈 노트 자체의 고유 permalink가 아니다.

사용자가 언급한 이전 실패(`httpx_html`, `post_id_unique`)도 같은 구조에서 온다. `li`만 row로 잡으면 날짜와 안정 ID가 부족하고,
`h3`만 row로 잡으면 title/summary가 실제 릴리즈 노트 행이 아니다.

## 해결
`AnthropicDocsReleaseNotesAdapter`를 추가했다.

- static httpx로 overview HTML을 가져온다.
- `#content-container`의 direct child를 순회한다.
- `h3`를 만나면 현재 날짜로 저장한다.
- 다음 `ul > li`들을 개별 release-note row로 만들고, 저장된 날짜를 `published_at`에 carry 한다.
- `post_id`는 `date_text + url + row text`의 SHA1 앞 20자로 만든다.
- 본문은 개별 `li` HTML/summary를 그대로 사용한다. 릴리즈 노트 bullet 자체가 게시물 본문 역할이다.

config:

```
configs/host_docs-anthropic-_en_571d0ac4.json
```

strategy:

```
handwritten / AnthropicDocsReleaseNotesAdapter
```

recognizer도 추가했다. 단, 이미 triage에 들어온 slug와 N100 poll_state 이름을 바꾸지 않기 위해
`NAME="host_docs-anthropic-"`, `_slug_board="en"`로 두어 기존 fallback slug
`host_docs-anthropic-_en_571d0ac4`가 유지되게 했다. 더 설명적인 recognizer name을 쓰면 slug schema migration 대상이 된다.

## robots / polite_sleep
probe에서 `robots.txt`는 200이고 `crawl_delay=None`이었다. config/adapter는 `polite_sleep` 3~6초를 사용한다.
일 1회 폴링 + 단일 HTML fetch라 `docs/크롤링 지침.md`의 호출 최소화/간격 원칙에 맞는다.

## 회귀 검증
- `python scripts/probe_smoke.py --stage 3` → `112 / 112 OK`
- `python scripts/probe_smoke.py --stage 5` → `742 케이스 · 0 FAIL`
- `python scripts/register.py --config configs/host_docs-anthropic-_en_571d0ac4.json` → baseline 30건
- `python scripts/register.py "https://docs.anthropic.com/en/release-notes/overview" --force` → recognizer 경로 baseline 30건, config/state 모두 `host_docs-anthropic-_en_571d0ac4` slug로 생성
- slug stability: `url_to_slug(URL) == "host_docs-anthropic-_en_571d0ac4"`

샘플:

```
d683b4a672dbb899d9a2  2026-05-19T00:00:00+00:00  MCP tunnels is now available as a Research Preview...
6fd1936c19649ec7096b  2026-05-19T00:00:00+00:00  Self-hosted sandboxes are now available...
8ea08187b5f6ae843da9  2026-05-19T00:00:00+00:00  With Claude Managed Agents, you can now update...
```

## 일반화 검토
- 2a platform recognizer: O. 같은 exact Anthropic release notes overview URL은 이후 probe/Gemini 없이 등록된다.
- 2b `--article-url`: X. 첫 글 URL 교정으로는 `h3` 날짜 carry 문제를 해결하지 못한다.
- 2c probe heuristic: X. "docs changelog의 preceding heading을 row metadata로 승격"은 generic config schema 범위를 넘는다.
- 2d probe bug: X. `og:type=article` false reject는 LLM veto가 막아야 하는 영역이지만, 이 케이스는 그 뒤에도 날짜 carry 때문에 handwritten이 필요하다.
- 2e handwritten config/adapter: O. 최소 동작 단위가 `h3 + following ul/li` stateful parse라 handwritten adapter가 가장 단순하다.

영향 사이트: 새 recognizer는 exact Anthropic release notes overview만 매칭한다. 같은 host의 일반 docs 페이지는 테스트에서 negative로 고정했다.
