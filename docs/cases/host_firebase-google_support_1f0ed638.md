---
slug: host_firebase-google_support_1f0ed638
url: https://firebase.google.com/support/releases
status: "⏸ deferred — 앵커-glob 단일페이지 (가치 낮음)"
outcome: no_change
date: 2026-05-21
failure_keys: [meta_diverging, posts_nonempty]
tags: [changelog, devsite, anchor-glob, deferred]
requested_by: catalog:2026-05-21-changelog
---

# firebase.google.com/support/releases — deferred

## 진단
- rc=1 gen_fail (probe timeout / posts_nonempty). DevSite 릴리스노트 = `h3` 날짜 + `div.changelog` 안의 항목들이 **한 페이지 앵커**(`#...`)로만 구분. 개별 글 permalink 없음.
- `schema.org/Article` 메타 때문에 `_meta_article_diverging_check` 구조 게이트가 단일-article 로 잡음.

## 거부 사유 (codex 위임 결과 reject)
codex 가 제안한 fix 2가지 모두 기각:
1. **`scripts/register.py` 에 `_static_changelog_index_shape` 게이트-escape 휴리스틱 추가** — CLAUDE.md §8a + ADR 0007(`[[project-llm-veto-reject-gates]]`) 위반. 게시판/비게시판 *판정* 을 구조 게이트에 사이트패턴 escape 로 박는 것은 금지 (분류기 layer 의 일 — `prompts/classify.system.txt`). SKILL §2c.
2. **body = `div.changelog` 통째 (~1.3MB/article)** — 앵커가 같은 페이지를 가리켜 모든 글이 전체 컨테이너를 본문으로 가져감. 비효율 + post_id 불안정.

## 왜 deferred (작업 X)
- 앵커 기반 단일페이지 changelog = 사용자가 2026-05-21 batch 에서 airflow/mysql relnotes 에 대해 "`<a>` 앵커 글 추적 어려움 / 가치 낮음" 판정한 패턴과 **동일**. post_id 가 앵커라 안정적 폴링 불가.
- RSS 대안 탐색 실패: `feeds/firebase-release-notes.xml`(404), `support/releases.xml`(non-feed HTML), `feeds/release-notes.xml`(404). cloud.google(`gcp-release-notes.xml`)과 달리 깨끗한 feed 없음.

## 트랙 B (미래)
- DevSite 앵커-glob changelog 의 일반 해법(앵커별 안정 post_id + 본문 분할)이 생기면 firebase·airflow·mysql·vscode 일괄 해결 가능. 현재 인프라론 가치 < 비용 → deferred.
