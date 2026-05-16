---
slug: host_scholar-google-_scholar_706d9c49
url: https://scholar.google.com/scholar?hl=ko&as_sdt=0%2C5&q=harness&btnG=
status: 🔧 손 config (작동중, baseline 10, httpx_html) + (C) probe heuristic + (D) retry feedback hint
outcome: improved
date: 2026-05-16
requested_by: poi23619
failure_keys: [article_body_len]
fix_layer: C+D
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/probe.py, generate/validate.py, tests/probe_heuristics/test_list_row_external_host.py]
tags: [search-result, aggregator, external-row-url, body-empty-acceptable]
---

## 무엇이 일어났나
사용자가 Google Scholar `harness` 검색결과 페이지에 `/preview` → 자동 등록 4회 retry 실패. `[FAIL] article_body_len: post_id=O9BF8Z9t-_EJ 0자 (<100)`. probe·parsing 다 통과해 list row 5건 정상 추출되었으나 (post_id=data-aid, title, url, author 다 OK), row 의 `url` 필드가 *외부 도메인* (`api.taylorfrancis.com/...pdf`, `books.google.com/...`, `en.bharatpedia.org/...` 등) 이라 article body 통합 추출 불가. last_config 의 `article.content` selector=`div.gs_ri` 는 list 페이지 안 element 라 외부 PDF/페이지 fetch 결과엔 없음 → 본문 0자 → hard-fail.

robots.txt 가 `/scholar` Disallow 명시하지만 register.py 정책은 warn-only 진행 (`docs/크롤링 지침.md`).

## 무엇을 바꿨나 (fix layer: C+D+손-config)

**(C) probe heuristic** — `probe/extract.py:list_row_external_host` 신규. list row 후보들의 `sample_url` host 가 `base_url` host 와 다른 비율 계산. child_count≥5 + 의미 있는 후보만 (pagination/sibling 페이지·http(s)아닌 url·href_is_js 제외). 산출 dict={base_host, total_count, external_count, external_ratio, sample_external_urls}. `probe/_contract.py` 에 `row_external_host` 필드 등록 (required=False, optional). `scripts/probe.py:write_list_candidates` 호출에 새 인자 박음. 새 키는 _PROMPT_REQUIRED_KEY_PATHS 에 등록 X — system prompt 변경 회피 (A-layer rot 위험).

**(D) retry feedback hint** — `generate/validate.py:_external_host_hint`. article_body_len fail 시 `post.url` host 가 `cfg.list.url_template` host (또는 `cfg.site`) 와 다르면 detail 에 hint 추가: "post.url host 가 list host 다름 → article 통합 추출 X. `article.skip_status:[200]` 박거나 article 섹션 생략." prompts 의 skip_status 룰 (line 81) 으로 LLM 이 다음 attempt 에서 skip_status 박을 수 있음.

**손-config** — `configs/host_scholar-google-_scholar_706d9c49.json`. httpx_html, article 섹션 생략. list.fields = post_id(data-aid), title, url, author, summary(`div.gs_rs` abstract). polite_sleep 15~30s (Google rate-limit 강함). `--config` path 는 `fetch_articles=0` 이라 body 검증 skip 통과.

## 회귀 검증
- `python scripts/probe_smoke.py` → PASS 214 / FAIL 0 / WARN 4 (옛 probe 산출물 신호 — push 차단 X). stage 5: 22 파일 · 181 케이스 · coverage 24/24 (새 휴리스틱 picked-up).
- 새 휴리스틱 unit: 8/8 PASS (`tests/probe_heuristics/test_list_row_external_host.py`).
- `register.py --config` → baseline 10건, body_empty_at_baseline=True ("본문 추출 안 됨" 경고 정상). FAILED.json 및 triage_queue 자동 정리.

## 일반화 효과
같은 패턴 (`list row url 들이 외부 도메인 비율 ≥0.8`) 의 다른 검색결과/aggregator 사이트는:
1. probe digest 에 `row_external_host` 신호 자동 박힘 (preflight·LLM·미래 코드 활용 가능)
2. LLM 자동 등록 시 첫 attempt 본문 0자 fail → (D) hint 받아 다음 attempt 에서 `article.skip_status:[200]` 또는 article 섹션 생략 → 통과 가능

손-config 없이 자동 통과되는지는 다음 SERP/aggregator 사이트로 확인.
