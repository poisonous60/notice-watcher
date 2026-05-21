---
slug: host_animate-onlines_contents_ba74459f
url: https://www.animate-onlineshop.jp/contents/news/
status: "🚫 거부 (입력 URL은 404, 공식 공지 remap 후보도 현재 공개 목록 0건)"
outcome: rejected
date: 2026-05-22
fix_layer: none
failure_keys: [target_not_found, posts_nonempty, empty_official_notice_list]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [animate-onlineshop, url-dead, empty-board, rejected]
requested_by: batch
---

## 진단

- preflight: b-hit — 실패 뒤 `prompts/engine/probe/generate/engine/recognizers` 영향 영역에 `27ed350`, `5665fa8` 커밋이 있어 `register.py --reuse-probe`를 재실행했지만, 빈 RSS 후보로 다시 `posts_nonempty: 0건` 실패했다.
- screen-out: P2-ish — `list.html` title 이 `404 - ドキュメントが見つかりません。` 이고 본문도 `入力したURLのページは存在しません` 인 not-found shell 이다.
- diagnosis verdict: `TARGET_NOT_FOUND`
- robots: `User-agent: *`, `Crawl-delay: 1180` 확인. 차단/로그인/captcha 신호는 없고, stealth 대상이 아니다.
- 실패 분류: original URL dead + empty remap. 수동 config 로 해결 가능한 selector 문제가 아니다.

## remap 확인

원 URL `https://www.animate-onlineshop.jp/contents/news/` 와 `/news/` 는 모두 HTTP 404다.

루트 페이지의 현재 공지 메뉴는 `https://www.animate-onlineshop.jp/info.php` 로 연결된다. 해당 페이지와 모바일 표현(`/sphone/info.php`, iPhone UA)은 모두 정상 200이지만 공지 목록은 빈 상태다.

- PC: `.content_information_list ul` 안에 row 0건
- mobile: `お知らせがありません。`
- RSS: `https://www.animate-onlineshop.jp/rss` 및 `/rss/index.php` 는 channel만 있고 `item` 0건
- detail URL 예시(`info.php?id=100688`)는 접근 가능하지만, 미래 새 글을 발견할 공개 목록/API가 확인되지 않았다.

웹 검색 인덱스에는 과거 `info.php?id=...` 상세 페이지가 남아 있으나, 검색 결과를 poll source 로 삼을 수 없고 현재 사이트의 공개 목록은 비어 있다.

## 결과

config 없음. 현재 URL은 죽었고, 공식 remap 후보도 `posts_nonempty` 기준을 통과할 수 없다. 향후 `info.php` 목록 또는 별도 공식 feed/API에 row가 다시 노출되면 새 URL로 재등록 대상이다.

## 트랙 B 검토

- 2a recognizer: X — 플랫폼 공통 패턴이 아니라 단일 호스트의 stale URL + 빈 공지 목록이다.
- 2b first_article_url 교정: X — probe 가 첫 글을 잘못 잡은 것이 아니라 목록 후보 자체가 없다.
- 2c/2d probe/schema/prompt: X — `TARGET_NOT_FOUND` 와 빈 RSS는 이미 관측된다. 이번 케이스는 새 추론 신호 누락이 아니라 사이트 상태 문제다.
- 2e 수동 config: X — `info.php`와 RSS 모두 row 0건이라 작동 config를 만들 수 없다.

일반화 안 되는 이유: URL dead는 이미 `url_dead`/`TARGET_NOT_FOUND` 계열로 분류되는 상태이고, remap 후보의 빈 목록은 사이트별 현재 상태라 generic 휴리스틱을 추가할 근거가 없다.

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://www.animate-onlineshop.jp/contents/news/"` FAIL 확인: 빈 RSS 후보로 `posts_nonempty: 0건`.
- `probe_smoke`는 별도 실행 결과를 작업 로그에 남긴다.
