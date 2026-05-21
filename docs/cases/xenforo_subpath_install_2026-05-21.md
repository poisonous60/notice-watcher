---
slug: xenforo_subpath_install_2026-05-21
url: https://xenforo.com/community/
status: ✅ 자동 등록 (XenForo recognizer 서브폴더 설치 install path 보존 — /community/forums/-/index.rss)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/xenforo.py, probe/extract.py]
tags: [xenforo, platform-config, recognizer, rss, subpath-install, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`685c658` 의 XenForo recognizer (전역 RSS `<base>/forums/-/index.rss`) 는 **host-root 설치만**
가정 — `build_config` 가 URL 의 path 를 버리고 `scheme://host` 만 base 로 썼다. 서브폴더 설치
사이트 (`xenforo.com/community/` — RSS at `/community/forums/-/index.rss`, 20 items 확인) 는
host-root `xenforo.com/forums/-/index.rss` 를 만들어 404 → fetch_list 0건 → 폴백 → gen_fail.

이건 batch-2026-05-21-forums 의 deferred 트랙 B 후보 (이전 case `infra_discourse_root_form` 부록).

## 무엇을 바꿨나 (단일 변경, fix_layer F — recognizer install-path 보존)

### 1. `engine/recognizers/xenforo.py`
- `_install_path(path)` 신규 — URL path 를 세그먼트로 쪼개 첫 알려진 XF route 세그먼트
  (`forums`/`threads`/`whats-new`/`members`/`index.rss` 등 `_XF_ROUTE_SEGMENTS`) *앞* 까지를
  install path 로 반환. `/community/forums/-/index.rss` → `/community`, `/whats-new/posts/` → ``.
- `build_config(base_url)` 가 path 에서 install path 보존 → `base = scheme://host{install}`.
  url_template·_source_url 자동으로 서브폴더 RSS. `_slug_board = host{install}` (동일 host 의
  root+subpath 설치 slug 충돌 방지).
- recognizer `_build` 가 full url 전달 (이전엔 host 만). `_RSS_RE`·`_WHATSNEW_RE` 정규식에
  `(?:/[\w-]+)*?` install prefix 흡수 추가 → 서브폴더 RSS/whats-new URL 도 직접 매칭.

### 2. `probe/extract.py` — `detect_xenforo_platform`
- 반환 `base_url` 에 install path 보존 (`_install_path` 재사용). probe-후 root-ish 서브폴더
  설치 (`xenforo.com/community/`) 도 register.py 가 올바른 RSS config 빌드.

### 3. 테스트
- `tests/recognizers/test_xenforo.py` — `subpath_install_preserved` + `subpath_rss_recognized` 2 케이스.
- `tests/probe_heuristics/test_detect_xenforo_platform.py` — `subpath_install_preserved` 1 케이스.

## 검증

- `recognize('https://xenforo.com/community/forums/-/index.rss')` → `/community/forums/-/index.rss` RSS config.
- `register.py` 로 등록 완료 — baseline 20건 (config `xenforo_xenforo.com_community_c56f7541.json`).
- 기존 host-root (hardforum/wordreference) 회귀 X — `build_config('https://hardforum.com')` 그대로
  host-root RSS. detect 의 avsforum `/whats-new/posts/?x=1` → install `` (route 세그먼트가 첫 seg).
- `probe_smoke.py --stage 3 --stage 5` PASS (stage 3: 94/94, stage 5: 0 FAIL · coverage 30/30).
  stage 1/2 의 7 FAIL 은 pre-existing stale fixture (skku/trickcal/arca/mabinogi — stash 비교로 확인, 본 변경 무관).

## outcome = handcrafted

fix_layer F (recognizer/플랫폼 config 확장). *알려진 플랫폼* XenForo 를 더 많은 설치 형태(서브폴더)
에서 인식만 확장 — generic 추론이 미지 유형을 푸는 게 아님. 직전 `xenforo` recognizer case 와 일관.

## 트랙 B 검토

이 변경 자체가 트랙 B (서브폴더 XenForo 재발 차단). recognizer install-path 보존이 본질이라
추가 휴리스틱 불필요.
