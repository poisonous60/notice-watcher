---
slug: host_square-enix-com_jp_50b6a465
url: https://www.square-enix.com/jp/magazine/
status: ✅ 손 config (작동중, baseline 9, httpx_html)
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, first_article_url_missing]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [square-enix, asia-newsportal, sitemap-candidate, static-html]
---

## 무엇이 일어났나
`[FAIL] posts_nonempty: 0건`. 입력 URL `https://www.square-enix.com/jp/magazine/` 자체는 JP magazine landing으로 렌더되고, probe 의 정적 후보는 `head > meta`뿐이라 글 목록 후보를 못 잡았다.

probe sitemap 후보에는 `https://www.square-enix.com/asia/newsportal/ko/`가 있었고, 자동 생성도 그 URL로 방향을 바꿨지만 일반적인 `article`/`.card`/`.news-item` selector를 반복해서 실제 row인 `li.c-list-entries-item`를 못 맞췄다.

## 무엇을 바꿨나
**단일 config**: `configs/host_square-enix-com_jp_50b6a465.json`
- 목록 URL: `https://www.square-enix.com/asia/newsportal/ko/`
- 목록 row: `li.c-list-entries-item`
- 글 링크: `a[href*='/asia/newsportal/ja/topics/'][href$='.html']`
- post_id: `/asia/newsportal/ja/topics/<category>/postN.html`
- 제목/날짜: `.c-list-entries-item-title`, `.c-list-entries-item-date`
- 본문: `.c-entry-body`, fallback `article`

## Track B 검토
누적 cross-check 는 `posts_nonempty`와 `first_article_url` 계열 모두 `track_b_trigger=true`였지만, 이 slug 의 직접 원인은 일반 selector 휴리스틱보다 **원 URL과 실제 등록 대상 URL이 다른 sitemap 후보 + Square Enix 고유 class 구조**에 가깝다.

recognizer 는 보류했다. `/asia/newsportal/ko/` 자체를 입력받는 반복 케이스가 아직 없고, 이번 URL(`/jp/magazine/`)을 곧바로 ko 뉴스 포털로 매핑하는 것은 사이트 고유 우회에 가까워서 broad recognizer 로 만들기엔 근거가 약하다. 같은 `asia/newsportal/{locale}` URL이 추가로 들어오면 locale별 recognizer 후보로 재검토한다.

## 회귀 검증
- `python scripts/register.py --config configs/host_square-enix-com_jp_50b6a465.json` → baseline 9건.
- `make_adapter` 손 실행 → list 9건, 첫 글 `elliot1000/post09.html`, body 1382 chars.

## 영향 범위
config 파일만 추가했다. engine/probe/prompt/recognizer 변경 없음.
