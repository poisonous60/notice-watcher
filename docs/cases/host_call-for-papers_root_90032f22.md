---
slug: host_call-for-papers_root_90032f22
url: https://call-for-papers.sas.upenn.edu/
status: 🚫 거부 (root는 안내 페이지 + 카테고리 메뉴, RSS는 빈 channel — 실제 CFP 목록 없음)
outcome: rejected
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, matches_probe_first_article, empty_feed, nav_category_menu]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [upenn-cfp, drupal, rss-empty, not-a-board, rejected]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a / §2g. probe가 sidebar category menu의 `/category/african-american`을 첫 글로 오인했다.
- 분기: 2e reject. root 본문은 CFP 사이트 로그인 장애 안내와 submit 안내이며, 실제 게시글 목록은 없다.
- preflight: b-hit — `register.py --reuse-probe` 재시도도 rc=1 `posts_nonempty`.
- cross-check: `posts_nonempty` 누적 67건, `track_b_trigger=true`; deferred 후보도 다수 true. 이번 케이스는 root/category URL 선택 문제라 별도 휴리스틱 추가는 보류했다.

## 확인

공개 RSS 후보 `https://call-for-papers.sas.upenn.edu/rss.xml`을 1회 확인했다. HTTP 200이지만 `<item>` 없는 빈 channel이라 feed config로 해결하지 않았다.

회귀 검증: config 없음. `probe_smoke --stage 3 --stage 5`로 기존 게이트 회귀만 확인.
