---
slug: infra_multi_host_hub_reject_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = _deferred_heuristics.md 의 `_multi_host_hub_check` lift)
status: 🏗 인프라 (multi-host hub 사전 거부 게이트 — tistory root 류 자동 reject)
outcome: improved
date: 2026-05-17
fix_layer: C+F+A
failure_keys: [multi_host_hub_root, deferred_heuristic_moving_target, tistory_root, plat_hub_unknown_host]
config_strategy:
adapters_changed:
engine_files_touched: [probe/extract.py, scripts/register.py, prompts/config_writer.system.txt, tests/probe_heuristics/test_list_row_external_host.py, docs/cases/_deferred_heuristics.md]
tags: [self-improvement, probe-heuristic, board-shape-gate, deferred-heuristic-lift, hub-rejection]
requested_by: 운영자 (dev box session)
---

## 트리거

이전 round (commit `33b01af` + `4672c42`) 후 사용자: "남은 2개 (_external_only_check 4건 / _multi_host_hub_check 3건) — 이건 뭔데". 신호 분포 분석 후 _multi_host_hub_check 만 박기로 결정 (`_external_only_check` 는 FP 위험 + 누적 4건 다 이미 인식기 cover — 박는 가치 0).

누적 cross-check (`cases_index.py query --deferred --json`):
- `_external_only_check` — 4건 (mdn/wiki-mirror/tistory/poly-pizza). 단 poly-pizza (total=1) 는 검증된 게시판 FP 위험. 임계 `total≥3` 하면 cover 안 됨.
- `_multi_host_hub_check` — 3건 (tistory root 가 진짜 hub. wiki-mirror/reject 인프라 는 단일 host).

→ `_multi_host_hub_check` 만 lift. `_external_only_check` 는 [검토 완료 — 박지 않기로] 표시.

## 픽스 (fix_layer: C+F+A — 5 파일)

### C-1. `probe/extract.py:list_row_external_host` — `multi_host_hub` 신호 추가

기존 출력 dict 에 2 필드 추가 (backwards-compat):
- `unique_external_hosts: list[str]` — sorted unique external netloc
- `multi_host_hub: bool` — `len(unique_external_hosts) ≥ 3 AND external_ratio ≥ 0.95`

검증 (4 누적 케이스):
- tistory root: 3 unique hosts (breezehu/ohokja1940/policy.daum), ratio=1.0 → True ✓
- poly-pizza: 1 unique host (wawasensei.dev sponsor), ratio=1.0 → False ✓ (FP 방지)
- github-wiki-see: 1 unique host (blizzard.cs.uwaterloo), ratio=1.0 → False ✓ (인식기 영역)
- developer-mozilla: 0 external, ratio=0.0 → False ✓

### F-1. `scripts/register.py:_multi_host_hub_check` 사전 거부 게이트

`_meta_article_diverging_check` 와 `_board_shape_check` 사이에 박음. `multi_host_hub=True` 면 즉시 rc=3 + `.REJECTED.json` 마커 + `learn=False`.

`learn=False` 이유: 호스트 root 가 hub 라도 *서브경로* (`*.tistory.com/<blog>`) 는 진짜 보드 가능. `_learn_pattern` 의 host+path_prefix 자동 차단이 그 보드까지 막을 위험. 인식기 PATTERNS_REJECT 가 명시 호스트 적으로 정확. 본 게이트는 구조 기반 fallback (인식기 미커버 새 hub 호스트 cover).

### A-1. `prompts/config_writer.system.txt` — 룰 *추가*

기존 `body_empty_likely` 룰 줄 다음에 새 줄 *추가* (수정/제거 X, skill §6.1.A 준수):

> list_candidates.row_external_host.multi_host_hub=true 이면 → **플랫폼 hub root** ... register.py 가 사전 REJECTED 마커 박아 여기까지 안 옴 — 만약 도달했으면 정책상 *등록 거부* 가 정답 ("게시판 아님" 으로 적어 멈춰라). aggregator/검색결과(`body_empty_likely`) 와 구별 = hub 는 *root 페이지 자체가 폴링 대상 아님* (개별 blog 서브경로는 보드일 수 있음).

### deferred_heuristics 정리

- `_multi_host_hub_check` → [lifted 2026-05-17 commit infra_multi_host_hub_reject]
- `_external_only_check` → [검토 완료 — 박지 않기로]

## 자가 점검 (§6)

1. **자리**: C (probe 신호 필드 추가) + F (register.py 사전 거부 게이트 추가 — board_shape 라인의 register.py 플로우 변경) + A (system prompt 새 줄 1개 *추가*).
2. **이전 케이스**: 위 cross-check 결과 — 3건 누적, track_b_trigger=true. `_deferred_heuristics.md` 의 `_multi_host_hub_check` 항목 = 2건째 트리거 (lifted).
3. **누구 깰까**: poly-pizza (FP 위험 검증 통과 — multi_host_hub=False), github-wiki-see (단일 host — multi_host_hub=False 안 잡힘, 기존 인식기로 reject). tistory root 만 게이트로 reject (기존엔 article_page_reject 인식기로 reject — 결과 동일, 이제 게이트로도 cover 가능).
4. **검증**:
   - probe_smoke 271 → 275 fixture, 0 FAIL
   - 4 누적 사이트 게이트 직접 호출 — tistory 거부 / poly-pizza 통과 / github-wiki-see 통과 / mdn 통과
   - 4 새 fixture (positive tistory + negative poly-pizza + threshold-2-hosts + ratio-below-threshold)
5. **outcome=improved, fix_layer=C+F+A, commit prefix `[fix-layer: C+F+A]`**.
6. **fixture**: list_row_external_host 의 신규 필드 (multi_host_hub) 4 fixture 추가. probe_smoke stage 5 28/28 coverage 유지.
7. **트랙 B 0건 사유**: 본 case 가 *직접 트랙 B 후보 lift*. 누적 cross-check 통해 추가 후보 없음.
