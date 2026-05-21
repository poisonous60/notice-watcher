---
slug: host_manta-net_en_7dc70a12
url: https://www.manta.net/en/notice
status: 🧩 수동 config — 죽은 manta.net URL을 Manta Comics Support Zendesk API로 remap
outcome: handcrafted
date: 2026-05-22
failure_keys: [probe_timeout, target_not_found, remap_to_api, cloudflare_challenge]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [manta, zendesk, remap, json-api, cloudflare]
requested_by: batch
---

## 무엇이 일어났나

원래 큐 항목은 `https://www.manta.net/en/notice` 이고, 실패 마커는 probe timeout 이었다.

`last_feedback`:

- `[FAIL] probe_timeout: probe timeout (120s)`

preflight:

- `configs/host_manta-net_en_7dc70a12.json` 없음
- recognizer 결과 `None`
- FAILED 이후 영향 영역 commit 2건:
  - `27ed350 [fix-layer: C+F] track-B: WordPress REST recognizer + soft-404 감지`
  - `5665fa8 [fix-layer: C] cloverworks news — extract: row multi-anchor picks best article href + www/non-www same site (httpx_html config)`
- 영향 영역 uncommitted 변경 0건
- `preflight: b-hit — host_manta-net_en_7dc70a12 27ed350`

`python scripts/register.py --reuse-probe "https://www.manta.net/en/notice"` 재확인 결과, 현재 URL은
도메인 root/robots 는 200 이지만 목록 URL 자체는 static/headless/captured-header 진입이 모두 404 다.

```text
Verdict: TARGET_NOT_FOUND
입력 URL 의 글이 존재하지 않음 — 모든 진입 시도가 HTTP 404
```

따라서 P1 content-as-list 오탐도 아니고 P2 soft-404 shell 누락도 아니다. 제출 URL이 죽었고,
현재 공지판은 검색 및 Zendesk API 확인상 Manta Comics Support의 Notice category 로 이동했다.

- category HTML: `https://help.manta.net/hc/en-us/categories/1500001609621-Notice`
- section API: `https://help.manta.net/api/v2/help_center/en-us/sections/1500002504202/articles.json`

HTML category/article 페이지는 httpx 에 Cloudflare `Just a moment...` 403 challenge 를 반환한다.
stealth 우회 없이 public Zendesk Help Center API가 목록을 제공하므로 JSON API config 로 remap 했다.

## 픽스

`configs/host_manta-net_en_7dc70a12.json` 을 `httpx_json` 으로 작성했다.

- 목록: Zendesk Help Center section articles API
- `post_id`: article `id`
- `title`: article `title`
- `url`: 사용자 브라우저용 `html_url`
- `published_at`: `updated_at`
- `summary`: API `body` 를 `html_unescape + collapse_ws`
- 본문: HTML article fetch 가 Cloudflare 403 이므로 `skip_status: [403]`, `body_empty_acceptable: true`

`help.manta.net/robots.txt` 는 Help Center article stats endpoint 만 disallow 하고, 사용한 section
articles API 경로는 명시 금지하지 않는다. `Crawl-delay` 는 없어서 config 에 5~8초 `polite_sleep` 를 둔다.

## Track B 검토

- **2a 인식기 — X.** Zendesk category/section id 가 Manta 전용이고, 새 shared recognizer 를 추가하지 않았다.
- **2b article-url — X.** 첫 글 URL 교정 문제가 아니라 제출된 board URL 이 404 인 remap 문제다.
- **2c/2d probe/prompt/engine — X.** 자동 solver 가 죽은 `manta.net/en/notice` 에서 `help.manta.net`의
  category id와 section id까지 안정적으로 추론할 근거가 없다.
- **2e 수동 config — O.** public Zendesk API를 쓰는 단일 host remap config 가 가장 작은 변경이다.

일반화 안 되는 이유: Manta의 old URL과 Zendesk Help Center category 사이의 브랜드별 remap이며,
generic 추론이 처음 보는 구조 유형을 더 풀도록 만드는 변경이 아니다.

## 회귀 검증

- `python scripts/register.py --config configs/host_manta-net_en_7dc70a12.json`
  - baseline 22건
  - 첫 3건:
    - `39250232522775` — `[Notice] Gem scale update on March 31, 2026`
    - `39545033137559` — `[Notice] Manga titles added to Manta as of April 7, 2026`
    - `35157607020823` — `[Notice] Manta Membership Launched on September 29, 2025`
- `make_adapter` smoke
  - `fetch_list(page_size=5)` → 5건
  - 첫 글 URL은 `https://help.manta.net/hc/en-us/articles/39250232522775--Notice-Gem-scale-update-on-March-31-2026`
  - 첫 글 `fetch_article()` body length 0, URL은 HTML article link 유지
- `python scripts/probe_smoke.py`
  - exit 1: 기존 artifact fixture 문제로 stage 1/2 실패
  - stage 3: `190 / 190 OK`
  - stage 5: `82 파일 · 883 케이스 · 0 FAIL · coverage 38/38`
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - exit 0
  - stage 3: `190 / 190 OK`
  - stage 5: `82 파일 · 883 케이스 · 0 FAIL · coverage 38/38`

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `probe_timeout` 은 3건으로 track-B trigger 상태지만, 이번 케이스는 재확인 결과
   `TARGET_NOT_FOUND` + host remap 이 원인이다. `url_dead` 도 3건 trigger 상태이나, 죽은 URL을
   특정 Zendesk API로 remap하는 단일 config라 shared gate/recognizer 변경 대상은 아니다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: register baseline 22건, make_adapter list 5건, stage 3/5 smoke 통과.
5. **outcome=handcrafted**: config selector/API path를 직접 고른 단일 수동 config 다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_json` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §Track B 검토 참조.
