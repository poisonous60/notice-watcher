---
slug: host_posthog-com_changelog_7d58ef58
url: https://www.posthog.com/changelog
status: 🧩 손어댑터 — Gatsby page-data JSON 을 최신순으로 뒤집어 changelog baseline 30건 등록
outcome: handcrafted
date: 2026-05-21
failure_keys: [title_nonempty, wrong_first_article_url, gatsby_page_data_oldest_first]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/posthog_changelog.py]
engine_files_touched: []
tags: [posthog, changelog, gatsby, page-data, json, newest-first]
---

## 무엇이 일어났나

`/changelog` probe 는 정적 HTTP 접근 자체는 가능하다고 판정했다. 하지만 HTML 반복 후보 상위가 실제 changelog 항목이 아니라 timeline/nav 성격의 `button` 반복과 `/` 링크였고, `first_article_url` 도 `https://www.posthog.com/` 로 잡혔다. 원 큐에서는 이 때문에 생성된 title selector 가 숫자/빈 값만 뽑아 `[FAIL] title_nonempty` 로 실패했다.

현재 로컬 재현은 Gemini API key 0개라 생성 단계에서 멈췄지만, probe 산출물의 구조는 같은 문제를 보여준다.

## 픽스

손어댑터 `PostHogChangelogAdapter` 추가:
- 목록은 `https://posthog.com/page-data/changelog/page-data.json` 의 `result.data.allRoadmap.nodes` 를 사용한다.
- 원 배열이 oldest-first 라서 `reversed(nodes)` 로 최신순 반환한다. 선언형 `httpx_json` 으로만 등록하면 baseline 이 2020년 항목부터 잡히는 문제가 있어 adapter가 필요했다.
- `post_id=id`, `title=title`, `published_at=dateT00:00:00+00:00`, `summary/content_html=description`, `url=cta.url` fallback `githubUrls[0]` 를 쓴다.
- robots.txt 는 named bot 의 `*.md`만 disallow 하고 `Crawl-Delay` 없음. adapter는 probe 권장 5초+에 맞춰 `polite_sleep` 5-8초로 둔다.

검증:
- `python scripts/register.py --config configs/host_posthog-com_changelog_7d58ef58.json` → baseline 30건 등록.
- `make_adapter` 스모크 → 최신 쪽 항목부터 5건 반환, title/post_id/date/url 모두 채워짐.

## 트랙 B (일반화 후보)

- **2a (인식기) — X.** PostHog 전용 사이트 구조라 플랫폼 recognizer 가치가 낮다.
- **2b (`--article-url`) — X.** first_article_url 오인은 맞지만, 실제 changelog 항목은 개별 article URL 중심 구조가 아니라 page-data JSON의 timeline row라 article-url 교정으로 해결되지 않는다.
- **2c/2d (probe 개선) — X.** Gatsby page-data 자체는 이미 `traffic_json_api_candidates`에 잡혔다. 실패는 JSON 내부 배열 정렬과 사이트별 row 의미 해석 문제라 일반 휴리스틱으로 박기 어렵다.

일반화 안 되는 이유: Gatsby page-data는 사이트마다 query shape와 sort semantics가 달라, 이번 변경은 PostHog 전용 adapter로 제한한다.

## 자가 점검 (§6)

1. **자리**: F (새 handwritten adapter + config).
2. **이전 케이스**: `title_nonempty` 2건, `wrong_first_article_url` 0건. 동일 root-cause 누적은 없음.
3. **누구 깰까**: 새 adapter는 `configs/host_posthog-com_changelog_7d58ef58.json` 에서만 참조되므로 기존 config 영향 0.
4. **검증**: register baseline 30건 OK, adapter list 5건 OK.
5. **outcome=handcrafted**: 알려진 단일 사이트의 dedicated adapter라 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy가 아니라 새 adapter라 `probe_smoke.py` stage 3 make_adapter 검증으로 충분.
7. **트랙 B 0건 사유**: 위 §트랙 B 참조.
