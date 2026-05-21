---
slug: host_fedia-io_root_1f0bc0d6
url: https://fedia.io/
status: "⛔ capability_blocked — root/combined가 login으로 redirect, mbin API도 401"
outcome: rejected
date: 2026-05-21
requested_by: batch
failure_keys: [capability_blocked, login_redirect, mbin_api_unauthorized]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [fedia, mbin, threadiverse, auth-required, capability-blocked]
---

## 무엇이 일어났나
`https://fedia.io/` 는 mbin/threadiverse 계열로 감지됐다(`list_candidates.mbin_platform.is_mbin=true`). 그러나 probe 의 모든 진입 경로가 로그인 페이지로 redirect 됐다.

summary:
- `S1.H2/H3/H4/Hcap`: `LOGIN_REQUIRED redirected to login`
- `S4`: `LOGIN_REQUIRED redirected to login`
- `S4.click`: clicked → `https://fedia.io/login`
- `list_candidates`: API/hydration/inline 후보 0건, nav 링크 `/combined` 만 존재

`python scripts/register.py --reuse-probe "https://fedia.io/"` 도 같은 capability_blocked 거부로 종료했다.

## API/RSS 확인
allow-list 밖 코드 변경 없이 공개 endpoint 가능성만 확인했다.

- `https://fedia.io/api/entries` → 401 `application/json`
- `https://fedia.io/api/magazines` → 401 `application/json`
- `https://fedia.io/feeds/entries.xml` → 404
- `https://fedia.io/combined.atom` → 404
- `https://fedia.io/combined.rss` → 404

현재 artifact 와 endpoint 확인 결과로는 인증 없는 list source 가 없다. OAuth/API credential 또는 로그인 세션 기반 capability 가 필요하다.

## 처리
config 는 작성하지 않았다. `httpx_json` 으로 `/api/entries` 를 쓰면 401 이고, HTML 경로는 로그인 화면만 반환한다. 이번 hard-stop allow-list 는 `adapters/`, `engine/`, `probe/`, `scripts/register.py` 변경을 금지하므로 mbin auth/storage_state capability 를 구현하지 않는다.

## 트랙 B
- 2a 인식기: 이미 `mbin_platform=true` 신호가 있다. 하지만 공개 API가 401이라 인식기만으로 해결되지 않는다.
- 2b `--article-url`: X. 목록 진입 자체가 login redirect다.
- 2c probe 휴리스틱: X. 신호는 이미 충분하다(`LOGIN_REQUIRED`, `mbin_platform=true`).
- 2d probe 오작동: X. endpoint 확인도 auth required 와 일치한다.
- capability backlog: mbin API credential 또는 storage_state 기반 adapter/capability가 생기면 재검토.

일반화 안 하는 이유: 문제는 추출 휴리스틱이 아니라 인증 capability 부재다. 새 capability 구현은 allow-list 밖이다.

## 검증
- `python scripts/register.py --reuse-probe "https://fedia.io/"` → exit 1, capability_blocked.
- endpoint HEAD 확인: `/api/entries`, `/api/magazines` 모두 401.
- 회귀 영향: 코드/config 변경 없음, case 기록만 추가.

