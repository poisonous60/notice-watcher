---
slug: _recognizer_commonwealth_2026-05-23
url: https://forum.sushi.com/discussions
status: "🧩 플랫폼 인식기 추가 (Common/Commonwealth SPA → tRPC API, Sushi baseline 확인)"
outcome: handcrafted
date: 2026-05-23
fix_layer: C+F
failure_keys: [common_platform_unrecognized, trpc_api_sushi_discussions]
config_strategy: handwritten
adapters_changed: [CommonwealthAdapter]
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/probe.py, scripts/register.py, engine/recognizers/commonwealth.py, adapters/commonwealth.py, adapters/__init__.py]
tags: [commonwealth, common, trpc, recognizer]
---

## 원인
Common/Commonwealth governance forum 은 Discourse 가 아니라 SPA shell + tRPC API 구조다. 정적 HTML 에는 글 목록이 없고 `<title>Common</title>`, `/assets/index-*`, `/brand_assets/common*`, `/api/internal/trpc` 같은 앱 shell marker 만 남아 자동 생성이 목록 0건으로 떨어졌다.

## 해결
fix-layer C: `probe.extract.detect_common_platform` 를 추가해 Common SPA shell 을 `list_candidates.common_platform` 으로 노출한다. URL path 의 첫 segment 가 community id 인 `common.xyz/<community>/discussions`, `commonwealth.im/<community>/discussions` 는 hint 를 채우고, `forum.sushi.com/discussions` 같은 custom domain 은 hint 없이 register 단계에서 domain API 로 확인한다.

fix-layer F: `CommonwealthAdapter` 를 추가해 `/api/internal/trpc/thread.getThreads` 를 직접 호출한다. `engine/recognizers/commonwealth.py` 는 `common.xyz`/`commonwealth.im` 의 명시 discussion URL 만 fast-path 처리하고, custom domain 은 false-positive 방지를 위해 probe detect 경로만 사용한다.

## 회귀 검증
영향 사이트는 `common.xyz/<community>/discussions`, `commonwealth.im/<community>/discussions`, 그리고 Common marker 가 실제 HTML 에 있는 custom domain 이다. Custom domain URL 은 URL pattern 으로 직접 매칭하지 않아 일반 `/discussions` 사이트를 가로채지 않는다.

검증:
- `python tests/probe_heuristics/test_detect_common_platform.py` PASS
- `python tests/probe_heuristics/test_recognizer_commonwealth.py` PASS
- `CommonwealthAdapter(base_url="https://forum.sushi.com", community_id="sushi").fetch_list(page=1, page_size=10)` baseline 10건 확인
- `python scripts/register.py "https://forum.sushi.com/discussions" --out output/codex_commonwealth_sushi_verify.json --force` rc=0, `common_detect`, baseline 20건 확인 (검증 artifact 는 정리)
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS
- `python scripts/vocab_lint.py` PASS

참고: full `python scripts/probe_smoke.py` 는 local `output/probe` 의 REPS artifact 부재로 stage 1/2 에서 실패했다 (`diagnosis.json 없음`/`digest.url 비어있음`). 이번 변경 범위인 pre-push subset(stage 3/5)은 통과했다.

## Track B
`python scripts/cases_index.py query --failure-key common_platform_unrecognized --json` 결과 local index 기준 count=0. 이번 케이스가 첫 Common platform 인식기 기록이다.

## 일반화하지 않은 것
`vocab_candidates` 는 추가하지 않았다. 이 케이스는 closed-vocab 확장이 아니라 알려진 플랫폼 전용 handwritten adapter + recognizer 경로다.
