---
slug: host_medium-com_feed_19419ab9
url: https://medium.com/feed/tag/programming
status: ✅ 등록 완료 (Medium tag RSS — httpx_html XML config + Medium recognizer)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, feed_candidates]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/medium.py]
tags: [medium, rss, recognizer, batch-2026-05-21-blogcms-gen3]
---

## 원인

자동 생성은 Medium RSS 응답을 봤지만 `body > item` / SPA selector 계열로 시도해 `[FAIL] posts_nonempty: 0건`을 반복했다. 실제 엔진은 `httpx_html`의 `parse_html_or_xml` 경로로 RSS/Atom XML을 이미 처리할 수 있고, 올바른 행 selector는 `channel > item`이다.

## 처리

- `configs/host_medium-com_feed_19419ab9.json` 추가: `https://medium.com/feed/tag/programming`을 RSS XML로 폴링한다.
- `engine/recognizers/medium.py` 추가: `medium.com/feed/tag/<tag>`와 publication URL을 Medium RSS config로 정규화한다.
- 기존 큐 slug 보존을 위해 recognizer `NAME`은 fallback platform segment인 `host_medium-com`을 사용했다. `url_to_slug("https://medium.com/feed/tag/programming")`는 그대로 `host_medium-com_feed_19419ab9`.

## 회귀 검증

- `python scripts/register.py --config configs/host_medium-com_feed_19419ab9.json` → PASS, baseline 10건.
- `python scripts/register.py "https://medium.com/feed/tag/programming" --force` → recognizer hit, baseline 10건.
- `python tests/recognizers/test_medium.py` → PASS.

## 트랙 B

RSS/feed signal 누적이 이미 많고 이번 케이스도 `feed_candidates`가 명확했다. Medium 전용 path-match recognizer로 같은 패턴 재발을 막았다. 일반 RSS strategy 확장은 필요 없었다. 기존 `httpx_html` XML parsing으로 충분했기 때문이다.
