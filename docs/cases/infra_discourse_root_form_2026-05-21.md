---
slug: infra_discourse_root_form_2026-05-21
url: https://forum.openwrt.org/
status: ✅ 자동 (probe generator-meta 휴리스틱 → DiscourseAdapter — root-form 봉합)
outcome: improved
date: 2026-05-21
fix_layer: C
failure_keys: [posts_nonempty, article_body_len]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/probe.py, scripts/register.py, engine/recognizers/discourse.py]
tags: [discourse, platform-recognizer, probe-heuristic, generator-meta, json-api, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`catalog=2026-05-21-forums` batch (100 사이트) 결과 — Discourse 포럼이 *root 도메인* URL 로 들어옴:
- `forum.openwrt.org/`, `forum.rclone.org/`, `forums.swift.org/`, `community.fly.io/`,
  `forums.developer.nvidia.com/` — 모두 rc=1 (`posts_nonempty: 0건` 또는 `article_body_len: 본문 못 얻음`).
- `community.cloudflare.com/` — rc=-2 (300s timeout; Cloudflare 보호 → `/latest.json` 도 0건. 정책상 거부 유지).

추가로 `2026-05-20` batch 의 `/latest`-form Discourse 5건이 *stale* FAILED.json 으로 남아있었음
(`discuss.python.org/latest` 등 — recognizer fix `2026-05-20` *이전* 시각 00:03 에 실패. 코드는 이미 회복).

### 진단 (§2 진입 강제 인용)

1. last_feedback `[FAIL]`: `[FAIL] posts_nonempty: 0건` (forum.openwrt root)
2. diagnosis verdict: `정적 HTTP로 충분` / rec_strategy `httpx (S1.H2)` — probe 가 Ember.js shell 을
   정적 OK 로 오판, topic rows 정적에 없음.
3. 실패케이스 §매칭: discourse.py docstring §9 (Ember shell → 정적에 row 없음 → posts_nonempty 0).
   기존 recognizer 가 root-form 미커버 = gap.
4. 분기: **2c (probe 휴리스틱) + F-layer**. 2a(recognizer 확장) 기각 — recognizer 는 URL-only
   pre-probe 라 bare root (`https://<host>/`) 를 안전하게 Discourse 판정 불가(모든 root 매칭 →
   false-positive 폭발). generator meta 는 probe *후* 에만 보임.
5. 누적 cross-check: `track_b_trigger=true` (signal `discourse|topic_list`, 기존 case
   `discourse_discuss.python.org`) → 트랙 B 진입 강제. deferred 보류 불가.
6. preflight: `b-hit` — /latest stale 5건 (failed_at 00:03 < recognizer fix); root-form = `miss` → §2 진입.

## 무엇을 바꿨나 (단일 영구 게이트, fix_layer C)

### 1. `probe/extract.py` — `detect_discourse_platform(html, base_url)` 휴리스틱 신규
- 정적 HTML 의 `<meta name="generator" content="Discourse ...">` 정규식 검출 (순수, fetch X).
- 출력 `{is_discourse, base_url, version}` 또는 None. false-positive ~0 (Discourse 외 사이트는 안 박음).
- `write_list_candidates` 에 `discourse_platform` 키로 박음.

### 2. `probe/_contract.py` — `list_candidates.json` 의 `discourse_platform` 필드 (옵션) 추가.

### 3. `scripts/probe.py` — `detect_discourse_platform` 호출 + write 전달.

### 4. `scripts/register.py` — probe-후 Discourse 포지티브 검출
- `build_digest` 후, 정책 게이트 *후* (BLOCKED 은 그대로 거부), board-shape/nav 게이트 *전*.
- `discourse_platform.is_discourse` 면 `engine.recognizers.discourse.build_config(base_url)` 로
  DiscourseAdapter config 만들어 `_register_built_config` (recognizer 등록 코어 추출) 호출.
- fetch_list 0건/예외/검증 실패면 일반 파이프라인 폴백 (안전망 — cloudflare 가 여기서 폴백).
- `--gate-only` 는 skip (네트워크/write 회피).

### 5. `engine/recognizers/discourse.py` — `build_config(base_url)` public 함수 추출
- recognizer `_build`(`/latest` URL) 와 register.py 의 probe-후 검출이 같은 builder 공유.

### 6. `tests/probe_heuristics/test_detect_discourse_platform.py` — 6 케이스 fixture (coverage 30/30).

## 검증

- 10 사이트 등록 완료 (각 baseline 30건):
  - root-form (probe generator meta): openwrt / rclone / swift / fly.io / nvidia-dev
  - /latest stale (recognizer fast-path 회복): discuss.python / discuss.huggingface / djangoproject / freecodecamp / users.rust-lang
- `probe_smoke.py --stage 3 --stage 5` PASS (exit 0). 전체 stage 1/2 fail 은 pre-existing stale fixture (skku/trickcal/arca/mabinogi — hook 무관).
- cloudflare.com: adapter fetch_list 0건 → 폴백 → 정책 게이트 거부 유지 (우회 X, 정상).

## 트랙 B 검토 (이 변경 자체가 트랙 B)

- (2a) recognizer — root-form 은 URL-only 라 불가 (위 분기 4). 기각.
- (2b) `--article-url` — 무관 (목록 자체 문제).
- (2c) **probe 휴리스틱 — 본 변경의 본질.** generator meta = 페이지에 박힌 fact, 휴리스틱화 가치 high.
- (2d) probe 산출물 정상.

## 같은 batch 의 나머지 fail 분류 (이 PR scope 밖 — 별도 기록)

- **rc=2 policy_reject (12)**: Cloudflare/BLOCKED (evga, raspberrypi, slickdeals, ubuntuforums,
  linuxquestions, bogleheads, discuz, sevenforums, tenforums, thegearpage, ygosu, vanillaforums) —
  정책상 거부 (`docs/크롤링 지침.md`), 우회 X. **의도된 거부.**
- **rc=4 url_dead (4)**: fluxbb/zwift/tesla = CERT_OR_DNS_BROKEN (사이트 사라짐), rog.asus = 404
  (URL 오류). **의도된 거부** (카탈로그 URL 편집이 답).
- **rc=3 gate_reject (27)**: root-marketing-hub (XenForo/IPS 포럼 root — macrumors/head-fi/xda/
  nexusmods/hardforum/linustechtips 등), board_shape, nav-only, multi-host-hub. 대부분 *root 가
  서브포럼 nav 만 노출* → 의도된 거부 (서브포럼/whats-new URL 권장). **deferred 트랙 B 후보 → 부록.**
- **rc=1 non-Discourse gen_fail**: wordreference(XenForo)/invisioncommunity(IPS) 본문 fail,
  bobaedream/humoruniv/fredmiranda/eevblog 반복 hard-fail, etoland `SelectorSyntaxError: Malformed
  class selector` (LLM 이 tailwind 클래스 `ul.space-y-1.5` 의 점 미escape — D-layer retry feedback
  후보, deferred). 

### deferred 트랙 B 후보 (다음 세션)

- **XenForo / IPS recognizer (generator-meta 동형)**: XenForo root 도 `<meta name=generator
  content=XenForo>` 박음 — Discourse 와 같은 패턴. 단 공개 JSON API 없음 → `/whats-new/posts` HTML
  스크레이프 손어댑터 필요 (Discourse 보다 큰 작업). `docs/cases/_deferred_heuristics.md` 참조.
- **etoland selector-escape**: soupsieve 가 `ul.space-y-1.5` 파싱 실패 → rc=1 크래시. retry feedback
  에 "클래스명의 점은 `\\.` escape" 한 줄 또는 selector 적용 시 graceful 처리. tailwind 사이트 재발 가능.
