---
slug: host_comic-days-com_info_ba9e6887
url: https://comic-days.com/info
status: ✅ preflight b-hit 회복 + config 등록 (baseline 5건, httpx_html)
outcome: improved
date: 2026-05-21
requested_by: batch
failure_keys: [article_body_len, matches_probe_first_article]
fix_layer: C
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [comic-days, hatena, recent-entries, body-selector, preflight-b-hit]
---

## 무엇이 일어났나

`[FAIL] article_body_len: post_id=190000 0자 (<100 — content selector 의심)`.
자동 생성 config 는 archive 일자 페이지의 `section.archive-entry` 목록은 잡았지만, `post_id` 를 시간 `190000` 만으로 뽑고 `article.url_template` 을 `https://comic-days.com/info/entry/2026/05/19/{post_id}` 로 날짜까지 고정했다.

그 결과 첫 글은 보였지만 본문 fetch 대상과 selector 조합이 불안정했고, probe 의 `first_article_url=https://comic-days.com/info/archive/2026/05/19` 와 실제 entry URL 이 불일치한다는 경고도 같이 남았다.

## 무엇을 바꿨나

`preflight: b-hit — host_comic-days-com_info_ba9e6887 [5665fa8]`.
실패 이후 영향 영역 commit이 있어 `python scripts/register.py --reuse-probe "https://comic-days.com/info"` 를 먼저 실행했고, 현재 generator가 2번째 attempt에서 통과하는 config를 생성했다.

`configs/host_comic-days-com_info_ba9e6887.json`:
- 목록: `https://comic-days.com/info/` 의 `ul.recent-entries.hatena-urllist > li.recent-entries-item`
- `post_id`: `/info/entry/YYYY/MM/DD/HHMMSS` 전체를 사용
- 글 URL: `https://comic-days.com/info/entry/{post_id}`
- 본문: `div.entry-content`, `div.entry-body`, `div.archive-entry-body` fallback

## Track B 검토

누적 query 에서 `article_body_len` 과 `matches_probe_first_article` 는 모두 `track_b_trigger=true` 였다.
이번 slug 는 실패 이후 이미 들어온 `5665fa8` probe 개선으로 회복된 stale 큐라, 새 probe/schema/prompt/recognizer 변경은 추가하지 않았다. `feed_candidates` 에 RSS/Atom 후보도 있었지만 정적 HTML config 가 baseline 과 본문 검증을 통과해 더 작은 변경으로 종료했다.

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://comic-days.com/info"` → PASS, baseline 5건.
- `make_adapter` 손 실행 → list 5건, 첫 글 content_html 1664 chars.
- 영향 범위: 새 엔진/프롬프트 변경 없음. 생성 config 1건만 추가.
