---
slug: _bug_feed_discovery_filecoin_celo_2026-05-23
url: https://www.filecoin.io/blog
status: ✅ feed discovery 보강 + Medium custom-domain RSS detect 추가
outcome: improved
date: 2026-05-24
fix_layer: C+F
failure_keys: [feed_discovery_missing, medium_custom_domain_unrecognized]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [probe/discover.py, probe/extract.py, engine/recognizers/medium.py, scripts/probe.py, scripts/register.py]
tags: [gen-fail, feed-discovery, rss, medium-custom-domain, batch-2026-05-21-crypto]
---

## 무엇이 일어났나

`2026-05-21-crypto` batch 의 gen_fail 2건은 둘 다 공개 RSS가 있었지만 자동 등록 경로가 그 신호를 충분히 쓰지 못했다.

| slug | URL | RSS endpoint | 원인 |
|---|---|---|---|
| `host_blog-filecoin-i_root_4ab2d2a3` | `https://www.filecoin.io/blog` | `https://www.filecoin.io/blog/rss.xml` | root well-known path 중심이라 `/blog` page-local RSS 링크와 `/blog/rss.xml` fallback 누락 |
| `host_blog-celo-org_root_be5ae2cb` | `https://blog.celo.org/` | `https://blog.celo.org/feed` | Medium custom domain marker는 있었지만 recognizer/dispatch가 `medium.com/<publication>` 전용 |

## 진단

- fix 자리: Part A는 C(probe digest 신호), Part B는 C(probe detect) + F(recognizer/register dispatch).
- 이전 케이스: `python scripts/cases_index.py query --failure-key feed_discovery_missing --json` 결과 count=0, track_b_trigger=false.
- 일반화 판단: RSS 링크/path fallback은 generic probe 개선이다. Medium custom domain은 알려진 SaaS detect이지만 URL만으로 오탐이 커서 probe marker 기반 dispatch로 제한했다.
- 영향 범위: 기존 Medium recognizer(`medium.com/feed/tag`, `medium.com/<publication>`)는 기존 테스트로 보존. 신규 dispatch는 `medium_custom_domain` probe key가 있을 때만 동작하므로 WordPress/Discourse/XenForo/Lemmy/Mastodon/Misskey/Pixelfed/PeerTube/Mbin dispatch와 독립이다.

## 무엇을 바꿨나

- `probe/discover.py`: visible `<a>`/`<link>` href에서 RSS/Feed/Atom/XML 후보를 찾고, fetch 검증된 후보만 `page-feed-link`로 기록한다. 입력 path가 `/blog` 같은 board path이면 `/blog/rss.xml`, `/blog/feed`, `/blog/index.xml`, `/blog.rss` fallback도 검증한다.
- `probe/extract.py` + `scripts/probe.py` + `probe/_contract.py`: `detect_medium_custom_domain`을 추가하고 `list_candidates.medium_custom_domain`에 `{is_medium_custom, base_url, feed_url}`을 기록한다.
- `engine/recognizers/medium.py` + `scripts/register.py`: custom-domain feed URL을 Medium RSS XML config로 빌드하고 probe 후 known-platform dispatch에서 baseline 검증 후 등록하도록 연결했다.
- tests: `tests/probe_heuristics/test_discover_feed_links.py`, `tests/probe_heuristics/test_detect_medium_custom_domain.py`.

## 검증

- RED 확인: 두 신규 테스트가 각각 feed 후보 누락과 `detect_medium_custom_domain` import 실패로 실패하는 것을 확인.
- unit: `python tests/probe_heuristics/test_discover_feed_links.py` PASS, `python tests/probe_heuristics/test_detect_medium_custom_domain.py` PASS, `python tests/recognizers/test_medium.py` PASS.
- smoke: `python scripts/probe_smoke.py --stage 3 --stage 5` PASS — 198 configs OK, 87 files / 943 cases / 0 FAIL.
- full smoke: `python scripts/probe_smoke.py`는 stage 1/2 기존 대표 artifact 누락(`skku`, `trickcal`, `arca`, `mabinogi` diagnosis/digest)으로 FAIL 8. stage 3/5는 PASS.
- Filecoin live probe: `https://www.filecoin.io/blog` probe 결과 `feed_candidates.json`에 `https://www.filecoin.io/blog/rss.xml`이 `page-feed-link`와 `page-path-fallback`으로 기록됨. `_url_serves_feed("https://www.filecoin.io/blog/rss.xml")` True.
- Celo live probe: `list_candidates.medium_custom_domain.feed_url = https://blog.celo.org/feed`; `feed_candidates.json`에도 verified `/feed` 후보가 기록됨.
- Celo RSS config write-free baseline: `build_custom_domain_config("https://blog.celo.org/feed")` + `make_adapter().fetch_list(page_size=10)` 결과 10 posts.

## register 검증 메모

`scripts/register.py` full success path는 config와 `output/poll_state/`를 쓰므로 이번 hard-stop 범위에서는 직접 실행하지 않았다. 대신 같은 `medium_custom_domain_detect` dispatch가 호출하는 builder/config/adapter fetch를 쓰기 없이 검증했다.

## 트랙 B

`feed_discovery_missing` 기존 indexed case는 0건이라 트랙 B 강제 진입은 아니다. 이번 변경은 특정 사이트 config가 아니라 RSS/Medium custom-domain generic 회복 경로다.
