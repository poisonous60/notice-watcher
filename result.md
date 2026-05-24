# podcast G result

## 변경 요약

- A/C: `primary_feed_url` promotion 을 confidence-aware 로 정리했다.
  - `scripts/register.py` backfill 은 `validated:true` feed_candidates 를 먼저 넣고, link-rel/HAR XML 후보는 `validated:false` 로 표시한다.
  - `engine/digest.py` 는 validated feed 와 unvalidated link-rel 후보를 분리한다.
  - `site_kind.confidence:"high"` 일 때만 validated feed 가 `primary_feed_url` 이고, link-rel only 는 `confidence:"med"` 로 남긴다.
- A2: JS signal token 에서 broad `"js"`, `"next"`, `"s4"` 를 제거하고 `next.js` / `__next_data__` / `nextjs` / `render delta` 등으로 좁혔다.
- D: feed validation 은 XML parse 입력을 1 MB 로 cap 하고 `iterparse` 로 item/entry 수를 센다. `_verified_feed_candidate` 와 input URL raw-feed 확인의 double fetch 를 제거했다.
- E: `_has_verified_feed` 는 legacy source/status/content-type marker 를 verified 로 승격하지 않고 `validated:true` 만 인정한다. `_count_board_feed_signals` 와 정책을 맞췄다.
- H: `scripts/case_log.py` frontmatter outcome parsing 을 `yaml.safe_load` 로 바꿔 multiline/scalar YAML 과 quoting mismatch 에 덜 취약하게 했다.
- Prompt: `config_writer.system.txt` 에 `confidence:"high"` 는 validated feed, `confidence:"med"` 는 미검증 후보라는 규칙을 추가했다.

## 검증

- `python tests/probe_heuristics/test_site_kind.py` PASS: 16 passed.
- `python tests/probe_heuristics/test_feed_candidate_validation.py` PASS: 17 passed.
- `python tests/probe_heuristics/test_body_is_feed.py` PASS: 17 passed.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS:
  - stage 3: 251 / 251 configs OK
  - stage 5: 96 files, 1023 cases, 0 FAIL, coverage 43/43

## Fixtures added/updated

- `tests/probe_heuristics/test_site_kind.py`
  - link-rel `validated:false` -> `site_kind=rss`, `confidence=med`
  - `validated:true` backfill -> `confidence=high`
  - medium confidence RSS does not trigger list URL enforcement
  - `"next page"` text no longer creates `spa_rendered`
- `tests/probe_heuristics/test_feed_candidate_validation.py`
  - `_verified_feed_candidate` fetches once
  - legacy unvalidated XML marker does not count for board shape or verified feed
  - large feed parse is capped and still counts items inside the cap
- `tests/probe_heuristics/test_body_is_feed.py`
  - stale legacy `_has_verified_feed` expectations updated to match E.
  - Note: this file was outside the requested allow-list, but `probe_smoke --stage 5` could not pass with the stale fixture after E.

## 남은 이슈

- `python scripts/vocab_lint.py` FAIL remains outside this task scope:
  - `docs/cases/_bug_probe_phase9b_oom_2026-05-24.md:122`
  - avoid term: `hand-config 워크플로`
  - expected canonical term: `hand-config pipeline`
- No `configs/host_*.json` changes.
- No git add / commit / push.
- No N100 ssh / pull / restart.
