---
slug: _sports_generic_investigation_2026-05-25
status: investigation
date: 2026-05-25
tags: [investigation, generic-improvement-candidates]
---

# sports batch 공통 실패 조사 (2026-05-25)

## 범위

기준 명령:

- `python scripts/triage.py pull --skip-later --no-auto-defer`
- `python scripts/triage.py list --skip-later`

`failed_at >= 2026-05-25T05:00:00Z` 이고 sports batch URL 로 보이는 활성 항목은 27건이다. `F=-` 인 항목은 운영 호스트에도 활성 `.FAILED.json` 이 없고 `triage_queue.jsonl` 의 `register_tail` 만 남아 있어, 이 문서는 그 tail 을 근거로 분류했다. `host_indycar-com_News_e4c69ade` 만 로컬 `.FAILED.json` 과 `output/probe/<slug>/` 가 남아 상세 확인 가능했다.

주의: 이 조사는 per-site config 작성이 아니라 공통 개선 후보 보고다. `configs/`, `engine/`, `probe/`, `prompts/`, `scripts/`, `generate/` 는 수정하지 않았다.

## failure_key 요약

| failure_key | 건수 | slug 예 |
|---|---:|---|
| posts_nonempty | 14 | uefa, cafonline, legaseriea, mlssoccer, espn, bcci, wimbledon, itftennis, usab, fis-ski, worldtabletennis, si, transfermarkt, indycar |
| capability_blocked | 4 | europeantour, olympics, ittf, bleacherreport |
| fetch_list | 2 | usopen, masters |
| post_id_unique | 2 | biathlonworld, cbssports |
| post_id_stable_shape | 1 | jleague |
| article_body_len | 1 | atptour |
| article_body_len + post_id_stable_shape | 1 | the-afc |
| article_body_len + title_nonempty | 1 | euroleaguebasketball |
| probe_timeout | 1 | laliga |

전체 대상:

- `host_uefa-com_insideuefa_7fe174ff`
- `host_the-afc-com_en_6207897b`
- `host_cafonline-com_news_d50a05cb`
- `host_legaseriea-it_en_0ddf76db`
- `host_laliga-com_en-GB_bb18edb0`
- `host_mlssoccer-com_news_dec514dd`
- `host_jleague-co_news_af0a9ee7`
- `host_espn-com_soccer_e722316f`
- `host_bcci-tv_articles_eaad766f`
- `host_atptour-com_en_3dfed836`
- `host_wimbledon-com_en_GB_99c38821`
- `host_itftennis-com_en_bad4d98a`
- `host_usopen-org_en_US_ad97acdf`
- `host_europeantour-co_dpworld-tour_16ed0fbe`
- `host_masters-com_en_US_749a5209`
- `host_olympics-com_en_520ca7a7`
- `host_euroleaguebaske_euroleague_cb2c7c2a`
- `host_usab-com_news_b208f626`
- `host_biathlonworld-c_news_55138d07`
- `host_ittf-com_news_1effe40c`
- `host_fis-ski-com_news_d42eb04e`
- `host_worldtabletenni_news_2b23cbd7`
- `host_si-com_nba_5b4f9f05`
- `host_cbssports-com_nba_f14638a0`
- `host_bleacherreport-_root_bfaab388`
- `host_transfermarkt-c_aktuell_29abde15`
- `host_indycar-com_News_e4c69ade`

## 원인 그룹

### Group A: card hub / nav 후보가 목록으로 오인됨

**증상**: 최종 실패가 `posts_nonempty` 로 끝난 항목이 14건이다. tail 에는 `head > meta`, `head > script`, nav/footer/menu, sponsor carousel, club directory 같은 반복 후보가 상위에 있고, 실제 article row cluster 가 없거나 LLM 이 fake RSS/feed 또는 너무 좁은 selector 로 이동하다 0건을 낸다.

**slug**: `uefa`, `cafonline`, `legaseriea`, `mlssoccer`, `espn`, `bcci`, `wimbledon`, `itftennis`, `usab`, `fis-ski`, `worldtabletennis`, `si`, `transfermarkt`, `indycar`

**근거 예**:

- `espn`: 반복 후보가 editions/team/nav 위주이고 3회 모두 `posts_nonempty`.
- `mlssoccer`: footer club sites/nav 후보가 우세, `a.fm-card-wrap.-story` 는 중복 뒤 0건 selector 로 이동.
- `indycar`: 상세 artifact 기준 sponsor swiper 41건이 top이고, 실제 뉴스 row 는 10건 후보로 뒤에 있음. RSS endpoint 선택은 0건.
- `si`: nav/category 반복과 fake RSS 시도가 섞임.

**generic fix 후보**:

- (C) probe heuristic: `article_cluster_score` 와 `nav_or_sponsor_cluster_score` 를 분리해, 같은 host article path cluster 가 0이고 nav/sponsor/footer cluster 만 많은 hub 를 digest 에 명시한다.
- (F) engine/register gate: gen_fail post-mortem 에서 이미 `_heterogeneous_hub_check` 계열이 들어와 있다. 남은 작업은 이 sports queue 에 대해 cleanup/sweep 결과를 확인하고, current tail 에서 놓친 subtype 을 추가하는 것이다.
- (A/D) prompt/retry: 반복 `posts_nonempty` 뒤 fake RSS 또는 nav selector 로 돌아가지 말고, "article cluster 가 없으면 config 작성 중단 또는 JSON/API 경로로 전환" 을 retry feedback 에 더 강하게 넣는다.

**과거 영향**: `python scripts/cases_index.py query --failure-key posts_nonempty --json` 기준 127건, `track_b_trigger=true`.

### Group B: duplicate card zones로 `post_id_unique` 실패

**증상**: 같은 article link 가 wide/narrow 카드, hero/list, headline/supplementary block 에 중복 노출되어 `post_id_unique` 가 난다. 단순히 selector 를 넓히면 중복, 좁히면 0건으로 흔들린다.

**slug**: `biathlonworld`(중복 10건), `cbssports`(중복 5건). 보조 근거: `mlssoccer` 와 `indycar` 는 이전 attempt 에서 `post_id_unique` 후 0건으로 이동했다.

**generic fix 후보**:

- (C) probe heuristic: 같은 URL/path tail 이 여러 sibling selector 에 반복되는 비율을 `same_post_id_dedup_signal` 로 노출한다.
- (D) retry feedback: `post_id_unique` 반복 시 "row root 를 article wrapper 하나로 고르거나, `row_required_selector`/`exclude_selector` 로 hero/sidebar/promo zone 을 제외" 하는 concrete recipe 를 넣는다.
- (A) prompt: carousel/card reuse 사이트는 "wide selector + duplicate" 와 "narrow selector + 0건" 사이 sweet spot 을 찾는 규칙을 보강한다.

**과거 영향**: `post_id_unique` query 기준 17건, `track_b_trigger=true`. 관련 사례: `host_bbc-com_news_7e763da2`, `host_edition-cnn-com_root_82356c05`, `host_venturebeat-com_root_b5f7c603`, `host_cdjapan-co-jp_feature_ba56403b`.

### Group C: stable post_id 검증이 canonical slug를 false-reject

**증상**: 안정적인 URL slug 인데 너무 길거나, URL path 에 typographic apostrophe 같은 문자가 포함되어 `_STABLE_ID_RE` 에 걸린다.

**slug**: `jleague`, `the-afc`

**근거**:

- `jleague`: current branch 에 이미 `docs/cases/host_jleague-co_news_af0a9ee7.md` 와 config 가 있다. case body 에 따르면 URL 마지막 segment 가 200자를 넘는 canonical article slug 라 `post_id_stable_shape` false-reject 가 났다.
- `the-afc`: RSS `channel > item` 시도에서 `post_id_stable_shape` 가 반복되고, tail 에 D-layer `rss_post_id_from_link` recipe 가 발동했지만 여전히 `ta’zim` 같은 URL slug 또는 full URL shaped id 가 검증을 통과하지 못했다.

**generic fix 후보**:

- (E) validate: URL에서 온 canonical slug 와 title-derived free text 를 구분하는 source-aware validation 이 필요하다. 단순 cap 완화만 하면 title 전체를 post_id 로 쓰는 실수를 놓칠 수 있다.
- (D) retry feedback: RSS/HTML link path tail 이 Unicode punctuation 을 포함하면 percent-encoded path 또는 full URL hash/source fallback 을 쓰도록 recipe 를 보강한다.
- (B) few-shot: 긴 sports/news URL slug 를 안정 ID 로 쓰는 정상 예와, title concat 을 거부해야 하는 반례를 함께 둔다.

**과거 영향**: `post_id_stable_shape` query 기준 19건, `track_b_trigger=true`. 관련 사례: `host_edition-cnn-com_world_ae74b4db`, `host_news-google-com_rss_891e780a`, `host_jleague-co_news_af0a9ee7`, `host_nationalgeograp_root_2be4a852`.

### Group D: anti-bot / baseline blocked

**증상**: probe verdict 가 `CLOUDFLARE_PROTECTED_SITE` 또는 `BASELINE_BLOCKED` 이고, list 후보 0건으로 끝난다. 이건 selector/prompt 문제가 아니라 접근 능력 문제다.

**slug**: `europeantour`, `olympics`, `ittf`, `bleacherreport`

**generic fix 후보**:

- (F) strategy/adapter: stealth/storage_state 또는 hardened browser profile track. 단, N100 Linux headless 운영이므로 `headless:false` 는 금지한다.
- (C) probe heuristic: `BASELINE_BLOCKED` vs Cloudflare challenge vs IP block 을 더 구조화해 retry/prompt 쪽으로 보내지 않게 한다.

**과거 영향**: `capability_blocked` query 기준 36건, `track_b_trigger=true`.

### Group E: HTTP2/probe timeout/fetch_list transport 문제

**증상**: Playwright `Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR`, `probe_timeout`, 또는 fetch 단계 transport error 로 실패한다.

**slug**: `laliga`(probe_timeout), `usopen`(ERR_HTTP2), `masters`(ERR_HTTP2). `wimbledon` 도 attempt 중 ERR_HTTP2 뒤 0건으로 이동했다.

**generic fix 후보**:

- (F) engine strategy: HTTP2 protocol error 사이트에 대해 httpx fallback, browser context 옵션, 또는 domain-level transport hint 를 retry path 에 전달한다.
- (D) retry feedback: transport error 와 selector 0건을 같은 `posts_nonempty` 방향으로 섞지 않게 한다. fetch transport error 는 selector 미세 조정으로 풀리지 않는다.

**과거 영향**: `fetch_list` query 기준 7건, `probe_timeout` query 기준 11건.

### Group F: list는 잡히지만 article body/title extraction이 약함

**증상**: list 후보는 있으나 본문 fetch 가 0자이거나 JSON list item 에서 title 이 비어 있다. LLM 이 list API 와 article API를 함께 맞추지 못한다.

**slug**: `atptour`, `euroleaguebasketball`, `usab`, `si`

**generic fix 후보**:

- (C) probe digest: 첫 article re-probe 결과의 article body selector/API 후보를 list 후보와 같은 수준으로 노출한다.
- (D) retry feedback: `article_body_len` 반복 시 list selector 변경보다 `article.fetch_kind=json` 또는 `article.body_empty_acceptable` 여부를 먼저 검토하게 한다.
- (A) prompt: "목록은 정적 HTML/API, 본문만 SPA/API" 케이스의 우선순위를 높인다.

**과거 영향**: `article_body_len` query 기준 31건, `track_b_trigger=true`.

## 우선순위 top 3

1. **Group A: card hub / nav 후보 false-accept 정리**
   - sports 영향: 14건.
   - fix layer: C + F + D.
   - 이유: 최다 패턴이고, current code 에 이미 post-mortem gate 가 들어와 있어 검증/cleanup chunk 로 이어가기 쉽다.

2. **Group B: duplicate card zone dedupe 신호**
   - sports 영향: 최종 2건 + 이전 attempt 2건.
   - fix layer: C + D + A.
   - 이유: 기존 `post_id_unique` 17건과 BBC/CNN 계열 증거가 있어 track-B 조건을 충족한다. probe 신호와 retry recipe 가 같이 가야 LLM 이 wide/narrow oscillation 을 줄인다.

3. **Group C: source-aware stable id validation**
   - sports 영향: 2건.
   - fix layer: E + D.
   - 이유: `_STABLE_ID_RE` cap 64→200 이후에도 긴 canonical slug와 Unicode URL slug가 남았다. 단순 완화가 아니라 source-aware 예외가 필요하다.

차점: Group D anti-bot은 4건이고 과거 36건이라 크지만, stealth/browser profile track 이 별도 큰 작업이다. Group E transport timeout은 별도 engine reliability chunk 로 묶는 게 낫다.

## 권장 chunk 분리

- `sports-hub-gate-cleanup`: Group A. `_heterogeneous_hub_check`가 sports tail 을 실제로 rc=3/cleanup 하는지 확인하고, 누락 subtype 만 추가. 파일 후보: `scripts/register.py`, `probe/*`, 관련 tests.
- `duplicate-card-dedup-signal`: Group B. probe digest signal + retry feedback. 파일 후보: `probe/*`, `generate/generator.py`, `prompts/config_writer.system.txt`.
- `stable-id-source-aware`: Group C. URL-derived slug validation 보강 + tests. 파일 후보: `generate/validate.py`, `scripts/poll.py`, `tests/validate/*`.
- `anti-bot-headless-profile`: Group D. headless 유지 전제의 stealth/storage_state path. 파일 후보: `engine/strategies/playwright_html.py`, probe browser entry.
- `transport-and-article-body-retry`: Group E/F. ERR_HTTP2/probe_timeout 과 article body API handoff 를 분리해 retry feedback 으로 전달.

## allow-list 밖 개선 필요

이번 작업의 허용 범위는 이 조사 문서뿐이다. 위 chunk 후보들은 모두 `engine/`, `probe/`, `prompts/`, `scripts/`, `generate/`, `tests/` 변경을 요구하므로 여기서는 수정하지 않았다. per-site config 도 작성하지 않았다.
