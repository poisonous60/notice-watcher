---
slug: host_namu-wiki_RecentChanges_2370318a
url: https://namu.wiki/RecentChanges
status: "✅ 기존 손 config 동작 확인 — RecentChanges 목록 30건 baseline, 본문은 body_empty_acceptable"
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [post_id_stable_shape, matches_probe_first_article]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [namu-wiki, recentchanges, spa, body-empty-acceptable, preflight-a-hit]
---

## 무엇이 일어났나
`https://namu.wiki/RecentChanges` 자동 생성은 마지막 검증에서 `[FAIL] post_id_stable_shape` 로 실패했다. 자동 생성 config 가 `/w/<문서명>` URL-encoded 문서명을 `post_id` 로 쓰면서 공백/괄호가 포함된 문서명까지 안정 ID로 취급해 검증에 걸렸다.

probe digest 는 `verdict=캡처 헤더 주입 시 정적 가능` 이라고 했지만 notes 에서는 정적 응답이 빈 shell 이고 Playwright DOM 에서만 row-like 요소가 잡힌다고 보고했다. RecentChanges 는 위키 문서 diff/feed 성격이라 글 본문 알림보다 제목/URL 변화 감지가 목적이다.

## 처리
preflight `a-hit`: `configs/host_namu-wiki_RecentChanges_2370318a.json` 가 이미 존재했다. 새 probe 없이 `python scripts/register.py --config configs/host_namu-wiki_RecentChanges_2370318a.json` 를 실행했고 baseline 30건으로 등록 성공했다.

현재 config 는:
- `strategy=playwright_html`
- `row_selector: a[href^='/w/']`
- `post_id`: `/w/` 제거 + query/fragment 제거
- `article.body_empty_acceptable=true`

본문 추출은 일부 문서에서 실패할 수 있으나 RecentChanges 알림은 제목/URL 기준으로 동작한다.

## 트랙 B
- 2a 인식기: X. namu.wiki RecentChanges 단일 특수 페이지라 플랫폼 recognizer 로 넓힐 근거가 부족하다.
- 2b `--article-url`: X. 첫 글 URL 오인 경고가 있었지만 본질은 `post_id` 안정성/본문 무관 알림이다.
- 2c probe 휴리스틱: X. 이번 작업은 이미 있는 단건 config 검증이다. `post_id_stable_shape` 누적은 많지만 대부분 article/root reject 계열이고, 이 케이스에 맞는 generic 휴리스틱은 allow-list 밖 코드 변경이 필요하다.
- 2d probe 오작동: X. `first_article_url` 과 실제 추출 행이 달라지는 SPA timing 문제는 보였지만 config 동작에는 영향 없음.

일반화 안 하는 이유: namu RecentChanges 는 위키 문서명 자체가 알림 키라 숫자형 게시글 ID를 요구하는 일반 게시판 모델과 다르다. 단건 config 로 제한하는 쪽이 안전하다.

## 검증
- `python scripts/register.py --config configs/host_namu-wiki_RecentChanges_2370318a.json` → exit 0, baseline 30건.
- 회귀 영향: config-only 확인, engine/probe/prompt 변경 없음.

