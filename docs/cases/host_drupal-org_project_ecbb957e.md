---
slug: host_drupal-org_project_ecbb957e
url: https://drupal.org/project/drupal/releases
status: "✅ known-platform recognizer 등록 (baseline 30건, Drupal release-history XML)"
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, fastly_client_challenge, release_history_xml]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/drupal_project.py]
tags: [drupal, releases, xml, recognizer, capability-blocked]
---

## 무엇이 일어났나

`/watch https://drupal.org/project/drupal/releases` 는 기존 queue 에서 rc=1 gen_fail 로 들어왔다. 사용자 제공 실패 요약은 selector root를 잘못 잡아 `posts_nonempty` 계열 검증이 실패한 케이스였다.

이번 dev box 재-probe에서는 정적 GET과 Playwright 모두 200을 받았지만 실제 본문은 Drupal release list가 아니라 Fastly `Client Challenge` CAPTCHA 페이지였다. probe 결과:

- `diagnosis.json` verdict: `정적 HTTP로 충분`
- `list_candidates.json`: HTML 0건, JSON API 0건, first_article_url 없음
- `list.html`: `Client Challenge`, `Enter the characters seen in the image below`
- `feed_candidates.json`: `https://drupal.org/rss.xml` 발견. 단 전역 Drupal.org RSS라 project release list와 정확히 같지 않음.

## 무엇을 바꿨나

`engine/recognizers/drupal_project.py` 를 추가했다. `https://(www.)drupal.org/project/<project>/releases` 를 Drupal의 공식 release-history XML endpoint로 매핑한다:

`https://updates.drupal.org/release-history/<project>/current`

생성된 config는 `httpx_html` XML parsing을 사용한다.

- row: `project > releases > release`
- post_id: `version`
- title: `name`
- url: `release_link`
- published_at: Unix timestamp `date` -> ISO8601
- summary: `download_link`

HTML release page는 challenge에 걸리므로 `article.body_empty_acceptable: true` 로 두고 제목과 URL 중심 알림으로 등록했다.

## Track B 검토

- 2a known platform: 적용. Drupal project releases는 URL path만으로 공식 XML endpoint를 결정할 수 있다.
- 2b `--article-url`: X. 첫 글 오인이 아니라 목록 HTML이 Fastly challenge다.
- 2c probe digest: X. 공식 release-history endpoint는 probe artifact에 직접 노출되지 않았고, URL 규칙 기반 플랫폼 recognizer가 더 작다.
- 2d probe 오작동: 부분적으로 있음. challenge 페이지를 `OK`로 본 것은 한계지만, 이번 해결은 사이트별 공식 XML endpoint 사용이다.
- 2e 수동 config: 단일 config보다 recognizer가 낫다. 같은 Drupal project release URL에 재사용 가능하다.

## 회귀 검증

- `preflight: miss — host_drupal-org_project_ecbb957e`
- `last_feedback` 첫 `[FAIL]` 줄: 사용자 제공 queue 요약 기준 `posts_nonempty`/selector root 실패. 로컬 재현은 Gemini key 0개로 generation 전에 중단됐으나 probe artifact는 challenge root cause를 확인했다.
- `diagnosis.json` verdict: `정적 HTTP로 충분`
- 실패 케이스 매칭: `docs/config 자동생성 실패 케이스.md` §2a `[FAIL] posts_nonempty: 0건` — 목록 후보 0건, first article 없음.
- 분기: 2a/F known-platform recognizer — URL에서 공식 release-history XML을 결정 가능.
- 누적 cross-check: `posts_nonempty` 43건, `track_b_trigger=true`; deferred 중 `static_variant_rows_not_promoted` 등 trigger=true. 이번은 generic probe row promotion이 아니라 Drupal 공식 endpoint recognizer로 봉합.
- `python scripts/register.py "https://drupal.org/project/drupal/releases" --force` -> PASS, baseline 30건.
- `python tests/recognizers/test_drupal_project.py` -> PASS.

## robots / polite sleep

`docs/크롤링 지침.md` 원칙에 따라 HTML challenge를 우회하지 않고 공식 XML endpoint를 1회 호출한다. config에는 `polite_sleep: {min: 5, max: 7}` 를 둔다.
