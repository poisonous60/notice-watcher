---
slug: host_pearlabyss-com_ko-kr_21e98c22
url: https://www.pearlabyss.com/ko-kr/news/notice
status: 🟡 보류 — SPA fully shielded (API endpoint unknown without browser inspection)
outcome: no_change
date: 2026-05-20
fix_layer: none
failure_keys: [posts_nonempty, spa_no_api_hint]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: []
tags: [pearlabyss, spa-shielded, deferred, batch-2026-05-20]
---

## 무엇이 일어났나

catalog 2026-05-20 batch — 펄어비스 공지 페이지 `posts_nonempty: 0건` 4회 fail.

진단:
- 정적 HTML 10KB — `<meta>` / `<link>` 만. board article rows 0건.
- `__NEXT_DATA__` 없음, JSON API hint 없음, `_boardNo` 형식 link 없음.
- probe `list_candidates.json`: html_repeating_patterns 상위 2건만 (`head > meta` cc=19, `head > link` cc=11). traffic_json_api_candidates=0.
- probe `article_click.json`: clicked OK=None, resolved_url 이 `/ko-kr` (root 로 튕김). headless click 도 실패.
- list.screenshot 도 동일 10KB shell.

verdict: 진짜 SPA, API endpoint 가 정적 HTML / HAR 어디에도 노출 X. JS 실행 후에야 fetch 가 발생하지만 그 fetch 의 응답을 wait_selector 없이 잡기 어려움.

## 무엇을 바꿨나

**아무것도 — 보류.**

손-config 또는 손어댑터 가능한 길:
1. 브라우저 DevTools Network 탭에서 page load 시 발생하는 XHR 검사 → JSON API endpoint 찾기 → httpx_json config 작성. (사용자 손-inspection 필요.)
2. playwright + 충분한 wait_selector (예: `.board-list-item`) → screenshot 으로 selector 발견. Pearl Abyss 의 실제 selector 가 무엇인지 확인 필요.
3. RSS 또는 sitemap 확인 — `pearlabyss.com/robots.txt` 검사.

이 turn 에서는 user-facing 즉시 등록 (트랙 A) 도, 일반화 가능한 휴리스틱/인식기 (트랙 B) 도 발견 X. 단일 게임사 공지 사이트 — 미래 같은 패턴 1건 더 들어오면 (다른 게임사 SPA 공지) 그때 일반 패턴 휴리스틱 검토.

## 트랙 B 검토

- (2a) 인식기 — pearlabyss 단일 사이트, 일반화 X.
- (2b) `--article-url` 재시도 — first_article_url 자체가 없음 (probe 가 못 찾음). 사용자가 글 하나 URL 줘도 LLM 가 본문 selector 찾을 단서 0건.
- (2c) probe 휴리스틱 — 신호 자체 없음 (html=2 meta/link only). 휴리스틱 추가 불가능 (raw 에 없는 fact 는 추출 X).
- (2d) probe 산출물 — playwright DOM 도 동일 10KB shell. probe 가 더 캡쳐할 데이터 없음.

deferred reason: SPA API endpoint 가 정적 fetch + headless render 모두에서 발견 X — 사용자 browser-inspection 단계 필요.
