---
slug: host_docs-snowflake-_en_67510c90
url: https://docs.snowflake.com/en/release-notes
status: ✅ 등록 완료 (Snowflake docs release notes static HTML config)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, static_docs_release_notes]
config_strategy: httpx_html
tags: [snowflake, docs, release-notes, static-html, nextjs]
requested_by: unknown
---

## 원인

로컬에는 기존 `.FAILED.json`와 `output/probe/host_docs-snowflake-_en_67510c90/`가 없어서 full `register.py`를 재실행했다. 현재 dev 환경에서는 `GEMINI_API_KEY`가 없어 생성 단계가 `gemini_api`로 멈췄지만, 사용자 제공 실패 로그의 핵심은 `[FAIL] posts_nonempty`였다.

probe 결과는 사이트 접근 문제가 아니었다.

- `diagnosis.json` verdict: `정적 HTTP로 충분`
- 실제 목록 후보: `article[data-testid='article-content'] section[data-section='recent-feature-updates'] ul li` 54건
- `robots.txt`: 200, `crawl_delay=None`
- 첫 글 URL: `https://docs.snowflake.com/en/release-notes/2026/10_18`

자동 생성이 더 넓은 반복 후보나 잘못된 row selector를 선택하면 목록이 0건이 된다. Snowflake release notes의 실제 "Recent feature updates" 목록은 article 본문 안의 특정 section에 있다.

## 처리

`configs/host_docs-snowflake-_en_67510c90.json`을 추가했다.

- `strategy=httpx_html`
- `row_selector=article[data-testid='article-content'] section[data-section='recent-feature-updates'] ul li`
- `row_required_selector=a[href]`
- `post_id`는 `/release-notes/...` path에서 추출
- 날짜는 행 텍스트가 `May 26, 2026:`처럼 시작하는 경우만 ISO8601로 변환하고, 날짜 없는 행은 허용
- 본문은 article page의 `article[data-testid='article-content']`
- robots `Crawl-Delay`가 없으므로 `docs/크롤링 지침.md`의 기본 원칙보다 보수적인 `polite_sleep` 5~8초 적용

## 회귀 검증

- `python scripts/register.py --config configs/host_docs-snowflake-_en_67510c90.json` → PASS, baseline 30건
- 샘플:

```
2026/other/2026-05-26-tables-iceberg-query-using-external-query-engine-snowflake-horizon-writes-ga  2026-05-26T00:00:00+00:00  May 26, 2026: Apache Iceberg™ tables: Write support by using
clients-drivers/snowflake-cli-2026  None  Snowflake CLI (v3.18.0)
2026/other/2026-05-19-dbt-projects-on-snowflake-updates  2026-05-19T00:00:00+00:00  May 19, 2026: dbt Projects on Snowflake updates
```

영향 0개: 새 recognizer, adapter, probe heuristic, schema, prompt는 건드리지 않고 단일 config만 추가했다.

## 트랙 B

누적 cross-check에서 `posts_nonempty`와 `static_variant_rows_not_promoted` 계열은 이미 `track_b_trigger=true`였다. 다만 이번 케이스의 probe는 실제 목록 후보를 이미 `html_repeating_patterns`에 노출했고, 실패 원인은 Snowflake docs 페이지의 특정 section selector를 생성 config가 놓친 것이다.

일반화 보류 사유: "static docs site"라도 목록 DOM 형태가 사이트마다 다르고, 이 케이스는 schema나 probe 산출물 부족이 아니라 단일 사이트 selector 선택 문제다. 넓은 휴리스틱을 추가하면 nav/sidebar 반복 후보와 실제 release-note 행을 구분하는 판정 로직까지 건드려야 하므로 이번 단일 board 복구 범위를 넘는다.
