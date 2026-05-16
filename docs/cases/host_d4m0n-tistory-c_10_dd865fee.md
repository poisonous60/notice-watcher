---
slug: host_d4m0n-tistory-c_10_dd865fee
url: https://d4m0n.tistory.com/10
status: ✅ 일반화 완료 (probe verdict TARGET_NOT_FOUND 분리 — 같은 패턴 미래 자동 처리)
outcome: improved
date: 2026-05-17
fix_layer: C+D
failure_keys: [target_not_found_misclassified_as_blocked, verdict_target_404_falls_through]
config_strategy:
adapters_changed:
engine_files_touched: [probe/diagnose.py, scripts/register.py, tests/probe_heuristics/test_diagnose_target_not_found.py]
tags: [self-improvement, probe-verdict, target-not-found, blocked-false-positive, tistory]
requested_by: poi23619 (bot /preview)
---

## 무엇이 일어났나

봇 사용자 `poi23619` 가 `/preview https://d4m0n.tistory.com/10` 했고 register 가 다음 메시지로 거부:

> 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='분류 보류'). 차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음. 등록 거부.

사용자가 사용자 향 — 확인 요청: "진짜 접근 불가능한지 아니면 오탐한건지". probe artifact 보니:

- **baseline B1 (`https://d4m0n.tistory.com/`)** : 200 OK · 28KB
- **baseline B2 (`/robots.txt`)** : 200 OK
- **entry_matrix S1.H2/H3/H4/Hcap/S4** : 전부 404 NOT_FOUND

사이트(도메인) 는 살아있고 그 글 `/10` 만 404. 차단이 X — *URL 이 없을 뿐*. 비교용 `https://ndb796.tistory.com/84?category=1008423` 도 직접 받아보니 200 OK · 57KB — tistory 자체 차단 X.

## 왜 문제인가

`probe/diagnose.py:171-185` 의 verdict_parts 빌더가 다음 분기만 처리:
- baseline_bot_only → `CLOUDFLARE_PROTECTED_SITE`
- baseline_cert_broken → `CERT_OR_DNS_BROKEN`
- not baseline_ok → `BASELINE_BLOCKED`
- static/captured/headless OK 여부

baseline 200 OK + target 전부 404 인 케이스는 어느 분기에도 안 걸려 `verdict_parts=[]` → `"분류 보류"`. register.py 의 fallback 분기가 이걸 "차단(BLOCKED) 사이트" 메시지로 처리.

직접 영향:
- 사용자가 "차단 사이트구나" 오해 (실제론 URL 잘못)
- 운영자가 진짜 차단과 dead URL 구분 어려움

## 픽스 (fix_layer: C+D — 2 파일 + 1 테스트)

### C-1. `probe/diagnose.py` — TARGET_NOT_FOUND verdict_part 추가

`verdict_parts` 가 비어있고 `baseline_ok=True` 인데 target 시도 (static + headless + captured + s1l) 전부 `Classification.NOT_FOUND` 면 새 verdict_part 박고 note 추가:

```python
if baseline_ok and not verdict_parts:
    target_results = list(static_results)
    if headless is not None:
        target_results.append(headless)
    if captured_retry is not None:
        target_results.append(captured_retry)
    if s1l is not None:
        target_results.append(s1l)
    if target_results and all(r.classification == Classification.NOT_FOUND for r in target_results):
        verdict_parts.append("TARGET_NOT_FOUND")
        notes.append("baseline(도메인 루트) 은 OK 인데 입력 URL 의 모든 진입 시도가 404 — "
                     "사이트 차단이 아니라 그 URL 의 글이 존재하지 않음 (잘못된 URL 또는 삭제됨).")
```

`not verdict_parts` 조건이 핵심 — `CLOUDFLARE_PROTECTED_SITE`/`CERT_OR_DNS_BROKEN`/`BASELINE_BLOCKED` 가 이미 박힌 경우 그 verdict 가 우선. TARGET_NOT_FOUND 는 fallthrough 자리.

### D-1. `scripts/register.py:_policy_check()` — 새 elif 분기

```python
if not _entry_matrix_has_ok_list(digest):
    if "cert_or_dns_broken" in verdict:
        return False, [...]  # 기존
    if "target_not_found" in verdict:
        return False, [f"입력 URL 의 글이 존재하지 않음 — 모든 진입 시도가 HTTP 404 "
                       f"(verdict={digest.get('verdict')!r}). 도메인 자체는 정상이므로 사이트 차단이 아니라 "
                       "URL 이 잘못됐거나 글이 삭제된 것 — 게시판 목록 URL 또는 다른 글 URL 로 재시도."]
    return False, [...]  # 기존 BLOCKED fallback
```

### 테스트 — `tests/probe_heuristics/test_diagnose_target_not_found.py`

5 case fixture — diagnose() 직접 호출:
- baseline OK + target 전부 NOT_FOUND → verdict 에 `TARGET_NOT_FOUND` 박힘
- note 한국어 안내 박힘
- baseline OK + target 부분 OK → TARGET_NOT_FOUND 안 박힘 (정적 HTTP로 충분 verdict)
- baseline 도 NOT_FOUND → BASELINE_BLOCKED 우선 (target_not_found 안 박힘)
- baseline OK + target 다 BLOCKED_BOT → TARGET_NOT_FOUND 안 박힘 (NOT_FOUND only 조건)

## 영향

- **회귀 risk**: 0. 신규 verdict_part 는 `verdict_parts=[]` 일 때만 발동 (기존 verdict 우선). register.py 의 새 elif 도 `cert_or_dns_broken` 다음 자리 — 기존 두 분기 변경 X.
- **false positive**: `all(NOT_FOUND)` 조건이 명시적. 일부라도 OK / BLOCKED_BOT / UNKNOWN_ERROR 있으면 발동 X.
- **다른 사이트 혜택**: 미래에 사용자가 잘못된 글 URL (404) 로 `/preview`·`/watch` 하면 봇 메시지가 정확히 "URL 잘못 / 삭제됨 — 게시판 목록 URL 로 재시도" 안내. 봇 retraining 비용 0.

## 회귀 검증

- `python scripts/probe_smoke.py` → **305 PASS / 0 FAIL** (이전 300 → +5 = 신규 fixture 5 case · stage 5 31 파일 · 263 케이스 · coverage 28/28).
- 새 fixture 5 case 전부 PASS.

## 트랙 B 매칭 (자가 점검 §6.7)

이 케이스는 트랙 A (사용자 향) 와 트랙 B (일반화) 가 **동일** — 트랙 A 가 "사용자 입력 URL 이 404 이라 등록 불가" 메시지 정확화이고, 그 자체가 probe verdict 일반화. 사용자 사이트 별 손-config X (해당 글이 존재 X, 만들 게 없음). slug `host_d4m0n-tistory-c_10_dd865fee` 도 fix 배포 후 같은 URL 로 다시 들어오면 자동으로 새 메시지로 거부 — `.REJECTED.json` 마커 X (사용자가 글 다시 올릴 수 있으므로 영구 차단 X).

## 남은 정리

- N100 의 stale `output/poll_state/host_d4m0n-tistory-c_10_dd865fee.FAILED.json` + `triage_queue.jsonl` 의 해당 slug 줄은 다음 `register.py` 호출이 자동 정리 (`_save_state`). 별도 액션 X.
- 봇 사용자 (`poi23619`) 에 직접 알림 X — 다음 `/preview` 재시도 시 새 메시지로 자연 안내.
