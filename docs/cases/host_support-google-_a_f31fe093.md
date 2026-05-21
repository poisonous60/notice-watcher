---
slug: host_support-google-_a_f31fe093
url: https://support.google.com/a/table/7539891
status: 🚫 거부 (Google Support 도움말 table/article hub — same-host 반복 링크가 전부 nav 안에만 있어 게시판 아님)
outcome: rejected_with_policy
date: 2026-05-21
requested_by:
failure_keys: [posts_nonempty, not_a_board, nav_only_same_host]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [google-support, docs-site, nav-only, not-a-board, existing-gate]
---

## 무엇이 일어났나
사용자 제공 실패 신호는 `rc=1 gen_fail` 및 selector 실패 계열이었다. 로컬에는 기존 `output/poll_state/host_support-google-_a_f31fe093.FAILED.json`과 probe 산출물이 없어 N100 pull 없이 dev box에서 fresh probe로 재진단했다.

- `diagnosis.json`: `verdict=정적 HTTP로 충분`
- `list_candidates.json`: HTML 반복 패턴 13건, JSON API 후보 0건, hydration 후보 0건
- `first_article_url`: `https://support.google.com/admin/getting-started/editions/choose-your-google-workspace-edition`
- `nav_only_same_host`: `total_same_host=3`, `in_nav=3`, `outside_nav=0`

반복 링크 후보는 Google Support 문서의 좌측/상단 navigation 항목이고, main content 안에 폴링할 게시글 row가 없다. 사용자가 준 URL 자체도 release/changelog board가 아니라 Google Workspace edition 관련 도움말 table/article hub다.

## 무엇을 바꿨나
코드와 config는 변경하지 않았다.

기존 `scripts/register.py`의 nav-only same-host 게이트가 이미 이 URL을 비용 0 경로에서 거부한다.

```text
python scripts/register.py "https://support.google.com/a/table/7539891" --reuse-probe --gate-only
→ 등록 거부 — 단일 article (nav-only same-host)
```

그 결과 `output/poll_state/host_support-google-_a_f31fe093.REJECTED.json`이 생성됐다. 이유는 `single_article_nav_only 거부 (nav 안 사이드바 메뉴만 잡힘)`이며 `learned=false`다. 수동 config를 만들면 nav 메뉴 문서 링크를 게시글처럼 폴링하게 되므로 잘못된 등록이다.

## robots / polite_sleep
`https://support.google.com/robots.txt`는 200이고 `Crawl-Delay`는 없다. `Disallow`는 `/*/search`, `/*/apis`, `/*/api` 등이며 이번 URL 경로 `/a/table/7539891` 자체는 해당하지 않는다.

이번 케이스는 등록 거부라 config의 `polite_sleep` 설정 대상이 없다. probe 권장 폴링 간격은 5초+였지만 실제 폴링 config를 만들지 않았다.

## 회귀 검증
- `python scripts/probe.py "https://support.google.com/a/table/7539891" --lite` → PASS, probe 산출물 생성
- `python scripts/register.py "https://support.google.com/a/table/7539891" --reuse-probe --gate-only` → 기존 nav-only 게이트로 REJECTED

## 일반화 판단
추가 휴리스틱은 박지 않았다. 이 케이스는 이미 `nav_only_same_host` 게이트가 정확히 잡는다.

- 2a recognizer: X. Google Support 도움말 문서 table은 게시판 플랫폼이 아니다.
- 2b `--article-url`: X. 진짜 게시글 URL이 없다.
- 2c probe/gate 휴리스틱: X. 기존 휴리스틱이 충분하다.
- 2d probe artifact 수정: X. probe가 nav-only 신호를 정확히 추출했다.
- 2e 수동 config: X. config를 만들면 navigation 문서 링크를 잘못 폴링한다.
