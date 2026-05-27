---
slug: _chunk-agentic-list-api-detection-2026-05-27
url: -
status: "✅ improved — traffic_json_api_candidates 가 *_id snake/Id camel 매처 + sTitle/iInfoId 등 prefix variant + cross-host sister-brand 통과"
outcome: improved
date: 2026-05-27
fix_layer: C
failure_keys: [traffic_json_api_candidates_zero, looks_like_row_id_keys_strict, looks_like_row_title_keys_strict, same_site_cross_brand_rejected]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/hydration.py, probe/extract.py, tests/probe_heuristics/test_find_list_in_json.py, tests/probe_heuristics/test_cross_host_list_api.py]
tags: [batch-2026-05-24-games-jp, agentic-improvement, cross-site-generalization, list-json-api, e2e-verified]
---

## 트리거 사이트 (cross-site 일반화)

같은 batch 2026-05-24-games-jp 의 3+ 사이트가 같은 패턴 — probe HAR 에 list JSON API 응답 명백히 있는데 `traffic_json_api_candidates: 0` → agentic 가 정적 HTML row_selector 만 시도 → fail. **§0c-0 1번 (agentic 자리 박기, cross-site generalization)** 적용. per-site hand-config 6건은 *최후 수단 봉합* 이었음 — agentic 자체 능력은 개선 X 였음. 이번 PR 이 *진짜* fix.

| slug | URL | list API (HAR 에 있음) | OLD `find_list_in_json` hits | OLD root-cause |
|---|---|---|---|---|
| host_granbluefantasy_news_8cb478ee | https://granbluefantasy.jp/news/ | `granbluefantasy.com/rcms-api/1/news` (`list[].topics_id`+`subject`+`inst_ymdhi`) | 1 (slug 키가 살려줌, 우연) → 0 candidate (cross-host filter) | `_same_site('granbluefantasy.jp', 'granbluefantasy.com')=False` 자매 brand 거부 + `_DATE_KEYS` 가 `inst_ymdhi`/`post_time` 미스 |
| host_umamusume-jp_news_14c28e10 | https://umamusume.jp/news/ | `umamusume.jp/api/ajax/pr_info_index` (`information_list[].announce_id`+`title`+`post_at`) | 0 | `_ID_KEYS` 가 `announce_id` 미스 (snake `_id` 패턴) |
| host_hoyoverse-com_news_e6028889 | https://www.hoyoverse.com/news/ | `sg-public-api-static.hoyoverse.com/.../getContentList` (`data.list[].iInfoId`+`sTitle`+`sDate`) | 0 | `_ID_KEYS` 가 `iInfoId` 미스 (camel `Id`) + `_TITLE_KEYS` 가 `sTitle` 미스 (Hungarian s-prefix) |

## fix layer 매핑 (§6 6 자리 위에서부터)

(E)/(D) 자리 없음. **(C) probe digest 신호 — `_looks_like_row`/`_looks_rowish` 의 키 매처 일반화 + cross-host structured guard**.

### C-1. `probe/hydration.py` 키 매처 일반화

| 신규 helper | 의미 |
|---|---|
| `_ID_KEY_RE = re.compile(r"^(?:[a-z][a-z0-9]*_id\|[a-zA-Z][a-zA-Z0-9]*[a-z]Id)$")` | snake `*_id` + camel `*Id` |
| `_TITLE_KEY_RE` | snake `*_title\|name\|subject\|headline` + camel `*Title\|Name\|Subject\|Headline` |
| `_DATE_KEY_RE` | snake `*_date\|time\|at\|on\|ymd\|ymdhi\|pubdate\|regdate` + camel `*Date\|Time\|At` + exact `ymd/ymdhi/created/...` |
| `_is_identity_value(v, *, url_like=False)` | value-shape guard — `{clientId: ""/null/[]/True}` stub 거부. int 또는 alphanumeric 2~128자 string. URL 키는 path/URL 문자 (`/`, `?`, `:` 등) 허용 |
| `_has_row_identity(d)` / `_has_title_key(d)` | fixed 집합 + 신규 regex 합쳐 매칭. `_looks_like_row` 와 `_looks_rowish` 가 공유 (codex review 권고) |

word-boundary 안전 — `grid`/`paid`/`void`/`splendid` 류는 `_id$`/`[a-z]Id$` 미스. `metadata`/`hostname` 는 `_TITLE_KEY_RE` 미스.

### C-2. `probe/extract.py` cross-host structured guard

`_cross_host_list_api_allowed(api_url, page_url, list_hits)` 헬퍼 신규. `traffic_api_candidates` 가 same-site 가 아니면 이 guard 통과해야 후보로 박힘.

**strict 조건** (codex review FAIL → REVISE 반영, *path keyword 단독* escape 거부):
1. **strong row semantic**: `sample_first` 에 title + identity + (url|date) 셋 다 보유. `{clientId: "abc", title: "Acme"}` 류 UI list 거부 (url/date 없음).
2. **brand match**: page registrable 의 첫 라벨 (e.g., 'granbluefantasy') 6자 이상 + api registrable 의 첫 라벨에 substring 포함 (양방향). 'abc'/'xyz' 같이 짧으면 거부 (false-positive 차단).

광고/트래커는 위에서 `_AD_TRACKER_RE` 가 hard filter — 여기 도달 자체가 안 됨. facebook/googleads/akamai 가 list-shape JSON 우연히 줘도 brand 미스로 거부 (negative fixture 박힘).

cross-host 후보 통과 시 `relevance_score -1` 패널티 (same-host preferred 정렬).

## codex review 반영 사항

1차 plan (path-keyword 단독 escape) → codex verdict `REVISE-RESUBMIT` (Fix B FAIL). 반영:

- ✅ key-only 매칭 → **value-shape guard** 같이 (`_is_identity_value`)
- ✅ `_looks_like_row`/`_looks_rowish` **공유 helper** (`_has_row_identity`, `_has_title_key`)
- ✅ cross-host escape **structured guard** (title+id+(url\|date) + brand match)
- ✅ **negative fixtures** (facebook notification, akamai CDN, generic clientId list, googleads 트래커)
- ✅ agentic e2e cost 축소 (codex review #5) — 1 cheap api-loop + 2 full auto 분배. 실제 결과: granblue/hoyoverse api_loop 1차 PASS (cheap), umamusume 만 agentic escalate

## 검증 (real artifact replay)

### NEW vs OLD `traffic_json_api_candidates` per slug

| slug | OLD count | NEW count | NEW top URL | NEW top score |
|---|---|---|---|---|
| host_granbluefantasy_news_8cb478ee | 0 | 1 | granbluefantasy.com/rcms-api/1/news | 7 |
| host_umamusume-jp_news_14c28e10 | 0 | 1 | umamusume.jp/api/ajax/pr_info_index | 7 |
| host_hoyoverse-com_news_e6028889 | 0 | 1 | sg-public-api-static.hoyoverse.com/.../getContentList | 7 |

### agentic e2e (`register.py --reuse-probe`)

| slug | api_loop 1차 결과 | agentic 결과 | 최종 strategy | baseline 건수 |
|---|---|---|---|---|
| granblue | **PASS 10건** (httpx_json) | (불필요) | httpx_json | 10 |
| hoyoverse | **PASS 7건** (httpx_json) | (불필요) | httpx_json | 7 |
| umamusume | FAIL (api_loop 가 httpx_html 잘못 시도, JSON parse err) | **PASS 30건** (httpx_json) | httpx_json | 30 |

published_at 도 자동 ISO 변환 (granblue `inst_ymdhi` → `2026-05-22T00:00:00+09:00`). 기존 hand-config 와 동등/우수.

### 회귀 (probe_smoke + pytest)

- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 1580 / FAIL 0 / coverage 48/48 (4 신규 heuristic 모두 fixture 박음).
- `python -m pytest tests/test_hub_gate_rss_escape.py tests/llm/test_register_auto_mode.py tests/fail_taxonomy/` → 17 passed.
- 기존 거부 케이스 unaffected (`looks_like_row_no`/`too_few_items`/`looks_rowish_missing_id` 등).

### Negative fixture (FP 회귀)

- `clientId` empty value `{clientId: ""}` → reject (value-shape guard)
- `paid: True` (bool) → reject (key + value 둘 다)
- `grid` / `id_token` / `IdRequest` → key regex 미스
- 자매 brand 짧은 (3자) → reject
- facebook `graph.facebook.com/notifications` cross-host → brand mismatch reject
- akamai CDN cross-host → brand mismatch reject

## 일반화 후보 / 미래 사이트 예상

같은 패턴 자동 회복 예상:
- 일본 게임 CMS — `*_id` snake 식별자 + `_ymd*`/`_time` 류 datetime (rcms, 자체 CMS 다수)
- 한국/중국 CMS — `iInfoId`/`articleId` camelCase Hungarian
- API host 분리 SPA — sister-brand `.com`/.io API 분리 패턴 흔함
- 다음 batch 의 같은 패턴 N 사이트 hand-config 작성 비용 0

## 후속 (commit `<this>`)

- per-site hand-configs (host_granbluefantasy_news / host_umamusume-jp_news / host_hoyoverse-com_news) = **이제 redundant**. agentic 자동생성 능력으로 봉합됨. 사용자 결정 후 삭제 가능 (덜 보수적이면 즉시, 보수적이면 N100 batch 재시도 후).
- capcom/drecom/shadowverse hand-configs = N100 stash 의 agentic 자동생성본과 비교 후 결정. 이번 fix 가 그 사이트들도 봉합하는지 별도 probe artifact pull → replay 필요.
