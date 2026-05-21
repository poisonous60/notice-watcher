---
slug: host_support-google-_a_f31fe093
url: https://support.google.com/a/table/7539891
status: 🚫 거부 (legacy Google Support table URL 이 단일 도움말 article 로 remap — 게시판 아님)
outcome: rejected
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty, not_a_board, nav_only_same_host, legacy_table_remap, content_as_list]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [google-support, docs-site, nav-only, not-a-board, legacy-table-remap, content-as-list]
---

## 무엇이 일어났나
batch `gen_fail(rc=1)` 로 들어온 케이스다. 원 URL:

```
https://support.google.com/a/table/7539891
```

현재 응답은 legacy Support table URL 에서 다음 단일 도움말 article 로 remap 된다.

```
https://support.google.com/a/table/7539891
  -> https://support.google.com/a/answer/6131189
  -> https://knowledge.workspace.google.com/admin/releases/ways-to-track-new-releases
```

`curl -L` 로 확인한 최종 HTML 의 canonical/og URL 도 `ways-to-track-new-releases` 이며,
title 은 `Ways to track new releases | Getting started | Google Workspace Help` 다. 즉 원 URL 은
살아 있지만 게시판/목록이 아니라 Google Workspace 도움말 단일 article 로 drift/remap 된 상태다.

`triage.py show host_support-google-_a_f31fe093` 의 실패 신호:

- `[FAIL] posts_nonempty: 0건`
- `matches_probe_first_article`: probe first article 과 생성 config 의 글 URL 불일치
- `count_ballpark`: 0건, probe 후보 `child_count≈50`
- 직전 3회 모두 `httpx_html` 로 nav selector 를 잡고 `posts_nonempty` 실패

- `diagnosis.json`: `verdict=정적 HTTP로 충분`
- `list_candidates.json`: HTML 반복 패턴 13건, JSON API 후보 0건, hydration 후보 0건
- `first_article_url`: `https://support.google.com/admin/getting-started/editions/choose-your-google-workspace-edition`
- `nav_only_same_host`: `total_same_host=3`, `in_nav=3`, `outside_nav=0`
- `article_meta_signals.is_article_page=true`, `schema_article_types=["Article"]`

반복 링크 후보는 Google Support 문서의 좌측/상단 navigation 항목이고, main content 안에 폴링할 게시글 row가 없다.
수동 config를 만들면 nav 메뉴의 도움말 문서 링크를 새 글처럼 폴링하게 되므로 잘못된 등록이다.

## 판정

screen-out: P1 content-as-list. legacy `/a/table/7539891` 이 실제 table/list board 를 반환하지 않고
단일 도움말 article 로 remap 됐으며, 자동 생성기는 article shell 의 navigation 링크를 목록으로 오인했다.

config 는 만들지 않았다. `configs/host_support-google-_a_f31fe093.json` 이 있으면 이 케이스에서는 오히려
잘못된 등록이다.

현재 작업 지시는 `output/poll_state/` 와 `output/triage_queue.*` 수정을 금지하므로, `register.py --gate-only`
를 실행해 `.REJECTED.json` 으로 치우는 작업은 하지 않았다. 운영자가 허용한 후 cleanup 단계에서 처리할 항목이다.

## robots / polite_sleep
`https://support.google.com/robots.txt`는 200이고 `Crawl-Delay`는 없다. `Disallow`는 `/*/search`, `/*/apis`, `/*/api` 등이며 이번 URL 경로 `/a/table/7539891` 자체는 해당하지 않는다.

이번 케이스는 등록 거부라 config의 `polite_sleep` 설정 대상이 없다. probe 권장 폴링 간격은 5초+였지만 실제 폴링 config를 만들지 않았다.

## 검증

- preflight: b-hit. 기존 config/recognizer 없음, FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` 영향 영역 커밋 존재.
- `python scripts/triage.py show host_support-google-_a_f31fe093` → 현재 FAILED + probe digest 확인.
- `curl -L https://support.google.com/a/table/7539891?hl=en` → 최종 canonical `https://knowledge.workspace.google.com/admin/releases/ways-to-track-new-releases`.
- `configs/host_support-google-_a_f31fe093.json` → 없음.

`register.py --reuse-probe --gate-only` 는 REJECTED marker 와 poll_state cleanup 을 쓰는 명령이라 이번 지시에서는 실행하지 않았다.

## 일반화 판단
추가 휴리스틱은 박지 않았다. 이 케이스는 이미 probe digest 에 `nav_only_same_host` 와 `article_meta_signals` 가 잡혀 있고,
Track B 변경 대상 파일(`prompts/classify.system.txt`, `probe/extract.py`, `scripts/register.py`, `engine/recognizers/*`)은
이번 지시의 allow-list 밖이다.

- 2a recognizer: X. Google Support 도움말 문서 table은 게시판 플랫폼이 아니다.
- 2b `--article-url`: X. 진짜 게시글 URL이 없다.
- 2c probe/gate 휴리스틱: 보류. 같은 유형을 자동 거부로 더 빨리 보내는 generic screen-out 여지는 있으나 shared 파일 작업이 필요하다.
- 2d probe artifact 수정: X. probe가 nav-only 신호를 정확히 추출했다.
- 2e 수동 config: X. config를 만들면 navigation 문서 링크를 잘못 폴링한다.

일반화 안 되는 이유: 이 URL은 특정 legacy Support table ID 가 현재 단일 Help article 로 remap 된 케이스다.
같은 host 전체를 recognizer 로 처리할 게시판 클래스가 아니며, 이번 작업에서는 case 기록과 거부 판정만 남긴다.
