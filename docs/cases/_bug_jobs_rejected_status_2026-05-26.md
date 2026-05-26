---
slug: _bug_jobs_rejected_status_2026-05-26
url: internal://jobs-status-rejected
status: "✅ improved — normal register rejects now finish as jobs.status='rejected'"
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys: [jobs_status_failed_overloaded, normal_rejects_counted_as_failed]
config_strategy: none
adapters_changed: []
engine_files_touched: [bot/db.py, bot/inspector.py, bot/admin.py, dashboard/app.py, tests/bot/test_jobs_schema_migrate.py]
tags: [bugfix, jobs, dashboard, batch, register]
---

## Evidence

From the 2026-05-26 retry batch:

```
failed rc=3: 1건 (app-liv.jp — catalog 정상 거부; 정확히 Problem 1 의 *증거*)
```

Across the first batch:

```
전체 첫 batch 분포까지 합치면 76 failed 중 약 52건이 *정상 거부* (rc=2/3/4, 게이트가 결정한
"비-게시판" / "url 죽음" / "LOGIN 정책"). 이것들이 status='failed' 로 묶여 distribution 이
왜곡됨 — 사용자 지적.
```

## Investigation

Canonical rc mapping is split across `scripts/register.py`, `bot/fail_taxonomy.py`, and ADR 0002:

- `rc=2`: `LOGIN_REQUIRED` / policy reject, written via `.REJECTED.json`.
- `rc=3`: gate reject, written via `.REJECTED.json`.
- `rc=4`: url dead / not found / cert-DNS / soft-404, written via `.REJECTED.json`.
- `rc=1`: generation or validation fail, written via `.FAILED.json`.
- negative rc including `-4`: system bug, written via `.BUG.json`.

The worker passes raw `register.py` rc into `db.mark_job_finished(conn, job_id, ok=(rc == 0), rc=rc, tail=tail)`.
Before this fix, `mark_job_finished` collapsed every non-zero rc into `status='failed'`.

`batch-register --failed` is rc-based, not status-based:

```
FAILED_PRESET_RCS = (1, 5, -1, -2, -3, -99)
```

So introducing `status='rejected'` does not cause normal rc=2/3/4 rejects to be retried.

## Fix

`bot/db.py` now maps terminal status from rc:

- `rc=0` / `ok=True` -> `done`
- `rc in (2, 3, 4)` -> `rejected`
- all other non-ok rc -> `failed`

The jobs schema and rebuild migration accept `rejected`, `queue_position` treats it as terminal, and dashboard `/jobs` can filter/display it as a base status.

## Regression

`tests/bot/test_jobs_schema_migrate.py` now verifies rc=2/3/4 finish as `rejected`, rc=1 remains `failed`, terminal queue position is `-1`, and summary counts include `rejected`.
