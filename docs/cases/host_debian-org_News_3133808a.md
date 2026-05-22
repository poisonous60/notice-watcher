---
slug: host_debian-org_News_3133808a
url: https://www.debian.org/News/
status: ✅ config 등록 (baseline 14, httpx_html)
outcome: recovered_by_preflight
date: 2026-05-22
fix_layer: none
failure_keys: [posts_nonempty, matches_probe_first_article, count_ballpark]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [debian, news, static-html, preflight-b-hit, generated-config]
---

## 무엇이 일어났나

`https://www.debian.org/News/` 자동 등록이 3회 retry 뒤 실패했다. 실패 표면은
`[FAIL] posts_nonempty: 0건` 이고, probe 는 첫 글 후보
`https://www.debian.org/News/2026/2026051602` 및 반복 패턴 `p > strong` 14건을 이미 잡고 있었다.

직전 자동 config 는 `row_selector: "#content > p > strong"` 까지는 맞췄지만 `post_id` 추출 regex 가
절대 경로 `/News/2026/...` 형태를 기대했다. 실제 row 의 `href` 는 `2026/2026051602` 같은 상대 URL이라
검증 단계에서 post_id가 비어 모든 row가 탈락했고, 결과적으로 `posts_nonempty: 0건`이 났다.

## preflight

SKILL.md §0b 적용 결과:

- 기존 `configs/host_debian-org_News_3133808a.json`: 없음
- recognizer: `None`
- 실패 이후 영향 영역 commit: `a9c5da5 feat(register): catalog 거부 + nav/연도-아카이브 오추출 게이트 (ADR 0011)`
- 결과: `preflight: b-hit — host_debian-org_News_3133808a [a9c5da5]`

`python scripts/register.py --reuse-probe "https://www.debian.org/News/"` 재시도에서 3회차 생성 config가
검증을 통과했고 baseline 14건으로 등록됐다.

## 무엇을 바꿨나

`configs/host_debian-org_News_3133808a.json` 추가.

- strategy: `httpx_html`
- list URL: `https://www.debian.org/News/`
- row selector: `#content > p > strong`
- post_id: 상대 링크 `2026/2026051602` 에서 최종 숫자 ID만 추출
- article content: `#content`

생성 직후 `post_id`가 `2026/2026051602`처럼 slash를 포함해 `scripts/demo_config.py` 덤프 파일명 생성에
실패했다. config의 `post_id` regex만 `^(?:\d{4}/)?(\d{8,})$` 로 좁혀 운영 ID를 `2026051602` 형태로
정리했다.

## 검증

- `python scripts/register.py --reuse-probe "https://www.debian.org/News/"` → PASS, baseline 14건
- `python scripts/demo_config.py configs/host_debian-org_News_3133808a.json --page-size 20 --articles 1` → PASS, fetch_list 14건, 첫 글 본문 52370 chars
- `python scripts/register.py --config configs/host_debian-org_News_3133808a.json` → PASS, baseline 14건

## 트랙 B

새 engine/probe/recognizer 변경 없음. 이번 케이스는 실패 이후 들어온 일반화 커밋 `a9c5da5`로 이미 회복된
preflight b-hit 확인 사례다. 같은 `posts_nonempty`/`matches_probe_first_article` 계열의 누적 trigger는
있지만, 이 slug에서 추가로 일반화할 새 신호는 발견하지 못했다.
