---
slug: host_fedia-io_root_1f0bc0d6
url: https://fedia.io/
status: "⛔ capability_blocked — root/combined가 login으로 redirect, mbin API는 현재 401; rc=5 Mbin rescue path 추가"
outcome: no_change
date: 2026-05-21
requested_by: batch
failure_keys: [capability_blocked, login_redirect, mbin_api_unauthorized, fediverse_api_rescue]
fix_layer: F
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [fedia, mbin, threadiverse, auth-required, capability-blocked]
---

## 무엇이 일어났나
`https://fedia.io/` 는 mbin/threadiverse 계열로 감지됐다(`list_candidates.mbin_platform.is_mbin=true`). 그러나 probe 의 모든 진입 경로가 로그인 페이지로 redirect 됐다.

summary:
- `S1.H2/H3/H4/Hcap`: `LOGIN_REQUIRED redirected to login`
- `S4`: `LOGIN_REQUIRED redirected to login`
- `S4.click`: clicked → `https://fedia.io/login`
- `list_candidates`: API/hydration/inline 후보 0건, nav 링크 `/combined` 만 존재

기존 `python scripts/register.py --reuse-probe "https://fedia.io/"` 도 같은 capability_blocked 거부로 종료했다.

## API/RSS 확인
allow-list 밖 코드 변경 없이 공개 endpoint 가능성만 확인했다.

- `https://fedia.io/api/entries` → 401 `application/json`
- `https://fedia.io/api/magazines` → 401 `application/json`
- `https://fedia.io/feeds/entries.xml` → 404
- `https://fedia.io/combined.atom` → 404
- `https://fedia.io/combined.rss` → 404

현재 artifact 와 endpoint 확인 결과로는 이 dev box 에서 인증 없는 list source 가 없다. OAuth/API credential 또는 로그인 세션 기반 capability 가 필요할 수 있다.

## 처리
config 는 작성하지 않았다. `httpx_json` 으로 `/api/entries` 를 쓰면 현재 401 이고, HTML 경로는 로그인 화면만 반환한다.

대신 rc=5 저장 직전 helper 를 `_try_fediverse_api_rescue` 로 일반화했다. Mbin 은 `/api/entries?sortBy=newest&perPage=10` 이 JSON list payload 를 반환하면 기존 `engine.recognizers.mbin.build_config()` 로 entries API config 등록을 시도한다. API 가 401/차단이면 기존처럼 capability_blocked `.FAILED.json` 로 폴백한다.

## 트랙 B
- 2a 인식기: 이미 `mbin_platform=true` 신호가 있다. 하지만 공개 API가 401이라 인식기만으로 해결되지 않는다.
- 2b `--article-url`: X. 목록 진입 자체가 login redirect다.
- 2c/F-layer: 적용. probe 신호가 없어도 rc=5 직전 Mbin public entries API 를 확인하는 rescue path 를 추가했다.
- 2d probe 오작동: X. endpoint 확인도 auth required 와 일치한다.
- capability backlog: Mbin API credential 또는 storage_state 기반 adapter/capability가 필요해지면 별도 작업으로 재검토.

일반화 범위: 공개 entries API 가 열려 있는 Mbin instance 만 자동 rescue 한다. 인증 capability 구현은 이번 범위가 아니다.

## 검증
- `python -c "from tests.probe_heuristics import test_fediverse_api_rescue as t; print(t.run())"` -> Lemmy/Mbin rescue unit PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` -> PASS 841, FAIL 0
- endpoint 확인: `/api/entries`, `/api/magazines` 모두 현재 401.

