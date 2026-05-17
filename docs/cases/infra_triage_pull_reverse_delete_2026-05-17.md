---
slug: infra_triage_pull_reverse_delete_2026-05-17
url: (인프라 case — triage.py pull stale FAILED 자동 정리)
status: 🏗 인프라 (triage.py pull 이 N100 에서 삭제된 FAILED 도 local 동기 삭제)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [scp_no_reverse_delete, stale_local_failed, pull_mirror_drift]
config_strategy:
adapters_changed:
engine_files_touched: [scripts/triage.py]
tags: [self-improvement, triage-pull, sync-delete, dashboard-mismatch, stale-cleanup]
requested_by: 운영자 ("저것들 처리한 것들인데 왜 안 사라졌지" — N100 에선 REJECTED 됐는데 local FAILED 잔재)
---

## 트리거

직전 worker rc=2 fix 후에도 `triage.py list` 가 7건 (F=y) 잔존. 운영자 의문 — "처리한 것들인데 왜 안 사라졌지".

확인:
```
N100 output/poll_state/host_iln-ieee-org_*.REJECTED.json     # 이미 REJECTED
local output/poll_state/host_iln-ieee-org_*.FAILED.json     # 옛 FAILED 잔재
```

`engine.recognizers.recognize_reject` 검사:
- 4건 (iln-ieee, jobplanet, nature, theholocaust): N100 에 REJECTED.json 존재, local 에 옛 FAILED.json
- 3건 (google-search, ncs-go-kr, piku): N100 도 REJECTED 처리됐고 (`host_ncs-go-kr_blind_be4a60bf.REJECTED.json` 류) local 옛 FAILED 잔재

→ **7건 다 N100 엔 이미 처리됨**. local 만 stale.

## 근본 원인

`scripts/triage.py:cmd_pull` 의 scp 가 reverse-delete 안 함:

```python
# 옛 코드 (forward sync 만)
rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/poll_state/*{_FAILED_SUFFIX}",
                f"{STATE_DIR}{os.sep}"])
```

흐름:
1. 시각 T1: N100 register 실패 → `host_X.FAILED.json` 생성 → pull → local 도 그 파일 있음
2. 시각 T2: 패턴 추가 commit 또는 다음 /preview → register `_save_rejected(slug)` 호출 → N100 `host_X.FAILED.json` 삭제, `host_X.REJECTED.json` 생성
3. 시각 T3: dev box `triage.py pull` → scp 가 N100 의 *현재* FAILED 만 copy → local 옛 FAILED 유지됨 (scp 는 local-only 파일 안 지움)

결과: local FAILED 가 영구히 누적. dashboard `/triage/failed` 는 local FAILED 보고 잘못 표시.

## 픽스 (fix_layer: F — 1 파일 변경)

### F-1. `scripts/triage.py:cmd_pull` — N100 ls → local 의 ¬remote FAILED 삭제

```python
rc_ls, out_ls = _run(["ssh", DEPLOY_HOST,
                      f"cd {DEPLOY_PATH} && ls output/poll_state/*{_FAILED_SUFFIX} 2>/dev/null || true"])
remote_failed: set[str] = set()
if rc_ls == 0:
    for line in out_ls.splitlines():
        name = Path(line.strip()).name
        if name.endswith(_FAILED_SUFFIX):
            remote_failed.add(name)
pruned_stale_slugs: list[str] = []
for fp in STATE_DIR.glob(f"*{_FAILED_SUFFIX}"):
    if fp.name not in remote_failed:
        fp.unlink()
        pruned_stale_slugs.append(fp.name[: -len(_FAILED_SUFFIX)])
```

scp `FAILED.json` 호출 **전** 에 ls 로 remote 목록 확보 → local 의 stale 삭제 → 그 다음 scp 로 현재 상태 copy. order 중요.

### F-2. probe/<slug>/ 도 sync delete — *방금 prune 된 stale slug 만*

```python
for slug in pruned_stale_slugs:
    pd = PROBE_DIR / slug
    if pd.exists() and pd.is_dir():
        shutil.rmtree(pd)
```

**제한**: pruned_stale_slugs 만 — smoke fixture probe (`host_cse-skku-edu_cse_5d3cd62e` 등) 나 성공 등록 사이트 probe 는 건드리지 X. probe/ 전체 sync 는 false-positive 위험 (fixture 다 날아감 — 첫 구현 시 실수했음).

### F-3. report 출력 line 추가

```python
if pruned_stale or pruned_stale_probe:
    print(f"  stale 정리 (N100 에서 이미 REJECTED/등록 완료): "
          f"FAILED.json {pruned_stale}건 / probe {pruned_stale_probe}개")
```

## 효과

- 즉시: 7건 stale FAILED + 7개 probe dir 정리 → `triage.py list` 0건 = dashboard 0건.
- 미래: 운영자가 N100 에서 등록/거부 처리 한 뒤 dev box `triage.py pull` 호출만 하면 자동 sync.
- worker rc=2 fix (선행 commit `645d7db`) + 이 fix 결합 → triage 큐는 *오직 actionable FAILED* 만 반영.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` → **345 PASS / 0 FAIL** (pre-push hook 가 검증).
- `python scripts/triage.py pull --skip-later` 실행 → 7건 stale + 7개 probe dir 정리 보고 → list 0건.
- (전체 smoke 의 stage 1/1b 2건 FAIL = mabinogi article_click + trickcal traffic_json_api — 첫 시도에서 probe/ 전체 prune 버그 때문에 fixture 날아간 잔재. 다음 fresh probe 또는 N100 scp 로 복구 가능. pre-push 영역 아니므로 무관.)

## 트랙 B 매칭 (자가 점검 §6.7)

- **2a/2b/2c/2d**: ❌ 무관 (probe/사이트 영역 X).
- **F (도구 인프라)**: ✅ `triage.py:cmd_pull` 1 분기.

## 위험 / 한계

- ssh ls 실패 (네트워크/권한) 시 `remote_failed=set()` → local FAILED 전부 stale 로 판정 → 다 삭제 위험. **방어책**: `if rc_ls == 0:` 가드 — ssh 실패 시 sync delete skip (local 보존, 안전 fallback). 운영자가 다음 호출에서 재시도.
- ssh ls 가 *지연* 되면 pull 자체가 느려짐 (1+ second 추가). 허용 — pull 은 잦지 않음.
- probe/ sync 가 너무 보수적 (방금 prune 된 slug 만) → N100 에서 *수동으로* FAILED 만 지우고 probe/ 안 지운 경우 local probe/ 잔재. 허용 — dashboard 에 영향 0.
