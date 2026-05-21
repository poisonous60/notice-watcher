---
slug: host_toranoana-jp_news_84973d13
url: https://www.toranoana.jp/news/
status: "✅ 수동 config (입력 URL은 404, 공식 news.toranoana.jp로 remap)"
outcome: handcrafted
date: 2026-05-22
fix_layer: none
failure_keys: [target_not_found, posts_nonempty, url_remap]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [toranoana, url-dead, remap, httpx-html]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] posts_nonempty: 0건`
- diagnosis verdict: `TARGET_NOT_FOUND`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a. 원인 ③ 목록 URL이 잘못된 경우다.
- preflight: miss — config/recognizer 없음. 실패 뒤 관련 영역 커밋은 있었지만, 기존 probe 재사용 상태의 마지막 실패가 이미 `TARGET_NOT_FOUND` + `posts_nonempty`였다.
- screen-out: P2-ish — `https://www.toranoana.jp/news/` 는 not-found shell 이며, 입력 URL 그대로 config를 만들면 안 된다.

## remap 확인

원 URL `https://www.toranoana.jp/news/` 는 HTTP 404다. 같은 사이트의 공식 인포메이션 인덱스 `https://news.toranoana.jp/` 는 200이고, 제목은 `とらのあな総合インフォメーション` 이다.

`https://www.toranoana.jp/rss.xml` 도 200이지만 2015년 항목 중심의 legacy Shift_JIS feed라 현재 news board source 로 쓰지 않았다.

robots: `https://news.toranoana.jp/robots.txt` 는 `Disallow: /wp-admin/`, `Allow: /wp-admin/admin-ajax.php` 만 두고 루트/글 경로를 막지 않는다. Crawl-delay 없음. config 는 보수적으로 `polite_sleep` 5초를 둔다.

## 결과

`configs/host_toranoana-jp_news_84973d13.json` 를 추가했다. `_source_url` 은 원 입력 URL을 남기고, 실제 `list.url_template` 은 `https://news.toranoana.jp/` 로 remap 했다.

목록은 `div.posts > div.post[id^='post-id-']` 에서 10건 확인했고, 첫 글 `348699` 본문은 `div.post-contents` 로 4909자 추출된다.

## 트랙 B 검토

- 2a recognizer: X — WordPress 계열처럼 보이지만 현재 recognizer가 이 루트 URL을 잡지 않고, 사용자 지시상 같은 트리 race 위험이 있는 `engine/recognizers/*` 수정은 하지 않았다.
- 2b first_article_url 교정: X — probe first article 문제가 아니라 원 입력 URL 자체가 404다.
- 2c/2d probe/schema/prompt: X — `TARGET_NOT_FOUND` 와 feed 후보는 이미 artifact 에 드러난다. 필요한 것은 selector 추론 개선이 아니라 사이트별 URL remap이다.
- 2e 수동 config: O — remap된 공식 목록 HTML이 정적으로 충분히 안정적이다.

일반화 안 되는 이유: stale URL 에서 공식 현재 URL로의 host remap은 사이트별 지식이다. generic 게이트는 이미 URL dead를 감지하므로 추가 휴리스틱 근거가 없다.

## 회귀 검증

- config schema validation: OK
- `make_adapter` smoke: list 10건, first article body 4909자
- `probe_smoke`는 작업 로그에 별도 결과를 남긴다.
