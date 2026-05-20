---
slug: infra_url_dead_split_2026-05-20
url: (인프라 — 분류 카탈로그 변경, 사이트 N/A)
status: ✅ 자동 (FailKind split — url_dead rc=4 분리)
outcome: improved
date: 2026-05-20
fix_layer: F
failure_keys: [target_not_found, cert_or_dns_broken]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: [bot/fail_taxonomy.py, scripts/register.py, dashboard/candidates_view.py, tests/fail_taxonomy/test_classify_fail.py, docs/fail 분류.md]
tags: [fail-taxonomy, rc-split, url-dead, dashboard]
---

## 무엇이 일어났나

catalog=2026-05-20 batch 결과에서 rc=2 (policy_reject) 26건 안에 **개념상 정책 위반이 아닌 케이스가 다수**:
- TARGET_NOT_FOUND (404 / URL 의 글이 사라짐): 14건 — 학교공지·게임사 공지·인벤 보드 등 카탈로그 URL 자체가 stale.
- CERT_OR_DNS_BROKEN (SSL/DNS fail): 3건 — 사이트가 사라짐.
- BLOCKED / LOGIN_REQUIRED (진짜 정책 거부): 9건.

`policy_reject` 하나로 묶으면 "정책 위반" 으로 표시돼 — 사용자는 *catalog yaml URL 편집* 이 답인 케이스와 *정책상 우회 불가* 인 케이스를 분간 못 함.

## 무엇을 바꿨나

### 1. `bot/fail_taxonomy.py` — 새 `FailKind url_dead`
- `rc=None`, `rc_extra=_url_dead_rc_extra` — `rc==4` (새 runs) OR `rc==2 + tail 에 TARGET_NOT_FOUND/CERT_OR_DNS_BROKEN 토큰` (옛 entries re-classify).
- Subkinds: `target_not_found`, `cert_or_dns_broken`.
- severity `warn` (정책 거부의 `error` 와 분리 — 사용자 액션 = catalog 편집).
- `FAIL_CATALOG` 순서: `gen_fail` → **`url_dead`** → `policy_reject` → `gate_reject` → `bug`. 순회 순서가 정확성 기반 — rc=2 + url-dead-tail entry 는 url_dead 가 먼저 잡고, BLOCKED tail 인 rc=2 는 url_dead skip → policy_reject 가 잡음.
- `rc_extra` signature 확장: `(status, rc) → bool` → `(status, rc, tail) → bool`. 기존 `_bug_rc_extra` / `_always_false` 도 무해 update.

### 2. `scripts/register.py` — `_policy_check` 거부 시 verdict 별 rc 분기
- `target_not_found` / `cert_or_dns_broken` verdict → `return 4` (새 `url_dead` FailKind 매칭).
- 그 외 (LOGIN_REQUIRED / BLOCKED) → `return 2` (기존 policy_reject 유지).
- `_save_rejected` note 에 `rc={rc_out}` 박음.

### 3. `dashboard/candidates_view.py` — 표시 어휘
- `STATUS_DISPLAY["url_dead"] = ("🔗", "URL 잘못/죽음")`.
- `STATUS_ORDER` 에 `gen_fail` 다음, `policy_reject` 앞에 `url_dead` 삽입.

### 4. `tests/fail_taxonomy/test_classify_fail.py` — 4 fixture 추가
- `url_dead_target_rc4`, `url_dead_cert_rc4` (새 runs).
- `url_dead_target_rc2_legacy`, `url_dead_cert_rc2_legacy` (옛 entries re-classify 회귀 차단).

### 5. `python scripts/gen_fail_taxonomy_doc.py` → `docs/fail 분류.md` 재생성. drift 차단.

### 6. retry 정책
- `register_batch.py:FAILED_PRESET_RCS = (1, -1, -2, -3, -99)` 에 4 미추가 — `--failed` 가 안 잡음 (의도). url_dead 는 *retry 무의미* — 같은 URL 재시도 = 같은 404. 사용자가 catalog yaml 에서 URL 편집 후 새 `untried` 로 enqueue 해야.

## 검증
- `python tests/fail_taxonomy/test_classify_fail.py` — 38/38 PASS (4 신규 fixture 포함).
- `python scripts/probe_smoke.py --stage 3 --stage 5` — 420 PASS / 0 FAIL.
- `docs/fail 분류.md` 재생성 — url_dead section 추가, drift 0.

## 사용자 액션 (이번 batch)
- 옛 26 rc=2 entries 가 dashboard `/candidates/2026-05-20` 에서 자동으로 re-classify (rc=2 + tail token = url_dead) — 코드 변경만으로 즉시 적용.
- 14 url_dead (target_not_found) entries 는 사용자가 catalog yaml URL 수정 후 새 batch.
- 9 policy_reject (BLOCKED/LOGIN) entries 만 진짜 우회-불가.

## 트랙 B 검토
- (A) prompts/system 수정 X.
- (B/F) FailKind split = F-layer (taxonomy infrastructure).
- 미래: rc=4 emit 패턴이 자리 잡으면 옛 rc=2-with-token 호환성 코드는 deprecated 가능 (1년 후 등). 지금은 둘 다 매칭.
