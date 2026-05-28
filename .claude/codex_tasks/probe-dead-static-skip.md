# Task: C-layer probe gate — skip Phase 2 headless when static results uniformly dead/error

## 배경 (cross-site, 의무)

batch `2026-05-24-games-mobile-strategy-rpg` (100 entries) drain 후 10 사이트가 `rc=5 cap_blocked (probe RSS OOM heavy SPA)` 로 분류됨. live 검증 결과 분류 오류:

| slug (host) | live GET status | live 본문 신호 | 진짜 분류 |
|---|---|---|---|
| `vikings.plarium.com` (×2 root/news) | HTTP 000 | connect refused/dropped | **url_dead** |
| `gunsofglory.com` (×2) | 200 (114 bytes) | JS redirect to `/lander` (marketing) | **url_dead** (no board) |
| `castleclash.igg.com` (×2) | 403 | anti-bot Forbidden | **cap_blocked** (진짜) |
| `familyfarmadventure.com/news` | HTTP 000 | connect dropped | **url_dead** |
| `longtugame.com` (×2) | 503 | persistent server unavailable | **url_dead** |
| `glu.com/news` | 404 | "404 - Official EA Site" | **url_dead** |

→ 8 url_dead + 2 anti-bot 인데 시스템이 *전부* rc=5 cap_blocked 으로 분류. 사용자 보고: 직접 사이트 들어가면 404 / 접속 안 됨.

## Root cause (scripts/probe.py:601-622)

Phase 2 (Playwright headless w/ HAR capture) 의 skip 게이트가 부족:

현재 skip 조건:
- `static_hard_login`: 정적 결과 전부 LOGIN_REQUIRED redirect
- `static_headless_skip_result`: 정적이 이미 skipworthy article rows 있음

**누락 게이트**: 정적 결과가 uniformly dead/error 일 때. 즉:
- 전부 4xx (404, 403 등)
- 전부 5xx (503 등)
- 전부 connection error (httpx ConnectError → status=0 또는 Classification.NETWORK_ERROR/UNKNOWN_ERROR)

이때 Phase 2 가 진행하면:
1. Playwright 가 같은 dead URL 로 goto → SPA shell load 시도
2. heavy marketing landing (gunsofglory `/lander` redirect 류) 또는 anti-bot interstitial 이 메모리 폭주
3. `probe.py:_start_memory_guard` (RSS > 3500MB) 가 self-kill → rc=99
4. `register.py:284 _run_probe` 가 `rc=99 → ProbeMemoryGuardError → caller rc=5 cap_blocked` 으로 분류
5. **실제는 url_dead 인데 cap_blocked 라벨** → triage Later 로 잘못 보내짐

## 작업: 새 skip 게이트 `_static_results_are_uniformly_dead`

### 1. `scripts/probe.py` 변경

`_static_results_are_hard_login` (line 319) 옆에 새 helper 추가:

```python
def _static_results_are_uniformly_dead(static_results: list[Result]) -> bool:
    """모든 static 결과가 4xx/5xx/connection-error 일 때 True.
    
    Phase 2 headless 가 같은 dead URL 로 escalate 해도 추가 신호 0 + 
    heavy SPA marketing redirect 가 OOM 유발 가능 (e.g. gunsofglory.com → /lander).
    
    True 면 Phase 2 skip → register.py 가 lite probe digest 만 보고 
    rc=4 url_dead 로 정확히 분류.
    """
    if not static_results:
        return False
    for r in static_results:
        # OK 200 또는 LOGIN_REQUIRED (별도 게이트 _static_results_are_hard_login 가 처리) 는 dead 아님
        if r.status == 200 and r.classification == Classification.OK:
            return False
        if r.classification == Classification.LOGIN_REQUIRED:
            return False
        # 200 이지만 redirect-only shell (body < N bytes) 면 dead 로 봄
        # — 단 이 케이스는 별 분기 (마케팅 redirect 감지) 로 후속, 지금은 status code 만 봄
    # 전부 4xx/5xx/0 인지 확인
    for r in static_results:
        is_4xx = 400 <= r.status < 500
        is_5xx = 500 <= r.status < 600
        is_conn_err = r.status == 0 or r.classification in (
            Classification.UNKNOWN_ERROR, 
            # 필요 시 NETWORK_ERROR 같은 classification 추가 — engine/probe Classification enum 확인
        )
        if not (is_4xx or is_5xx or is_conn_err):
            return False
    return True
```

⚠ `Classification` enum 확인 의무 (`probe/_contract.py` 또는 `engine/...`). NETWORK_ERROR 클래스 있으면 포함.

### 2. Phase 2 skip 분기 추가 (scripts/probe.py:606-611)

기존:
```python
static_hard_login = _static_results_are_hard_login(static_results)
static_headless_skip_result = _static_result_for_headless_skip(static_results, url=url)
if static_hard_login:
    print("\n[Phase 2] skipped — Phase 1 hard LOGIN_REQUIRED redirect (headless would hit login SPA)")
elif static_headless_skip_result is not None:
    print("\n[Phase 2] skipped — static HTML already has repeated article links")
elif _do_headless:
    ...
```

새 분기 *맨 위* (login 보다 먼저, dead 가 더 빠른 early-exit):
```python
static_uniformly_dead = _static_results_are_uniformly_dead(static_results)
static_hard_login = _static_results_are_hard_login(static_results)
static_headless_skip_result = _static_result_for_headless_skip(static_results, url=url)
if static_uniformly_dead:
    statuses = sorted({r.status for r in static_results})
    print(f"\n[Phase 2] skipped — static all dead/error (statuses={statuses}) — headless escalation would risk OOM on heavy SPA landing")
elif static_hard_login:
    ...
```

### 3. register.py 측 — 4xx/5xx 분류 정확화

`scripts/register.py:3015 except ProbeMemoryGuardError` 분기는 그대로 유지 (다른 진짜 SPA OOM 케이스 위해). 단:

- Phase 2 skip 가 도입되면 dead URL 은 OOM 까지 안 가고 lite probe 가 빠르게 완료.
- 이후 digest 에서 `diagnosis.json:verdict` 와 `recommended_strategy` 가 "정적/url_dead" 신호 박힘.
- `register.py` 의 기존 url_dead 분류 경로 (`scripts/register.py` 어딘가 4xx/5xx → rc=4 처리) 가 그걸 잡음.

⚠ **사후 검증**: 진짜 url_dead 분류 자리 확인:
- `grep -n "url_dead\|rc=4\|REJECTED.*url" scripts/register.py`
- 보통 `_save_rejected(slug, url, "url_dead: ...")` + `return 4` 패턴
- 4xx/5xx static results 가 register.py 어느 게이트에서 rc=4 로 떨어지는지 trace.
- 없다면 새 게이트 추가 (지금 task scope 안에서 — Phase 2 skip 후 register.py 가 적절히 rc=4 분류해야 함).

### 4. unit test 추가

`tests/probe/test_dead_static_skip.py` (new):

```python
"""_static_results_are_uniformly_dead 동작 검증."""
from probe._contract import ... # Classification, Result
from scripts.probe import _static_results_are_uniformly_dead

def run():
    cases = []
    # all 200 OK → False
    cases.append(("all_200", ..., False))
    # all 404 → True
    cases.append(("all_404", ..., True))
    # all 503 → True
    cases.append(("all_503", ..., True))
    # all 0 (connect err) → True
    cases.append(("all_connect_err", ..., True))
    # mixed 404 + 200 → False (some OK)
    cases.append(("mixed", ..., False))
    # all LOGIN_REQUIRED → False (다른 게이트)
    cases.append(("all_login", ..., False))
    # empty → False
    cases.append(("empty", ..., False))
    # 200 + 503 mixed → False (some OK)
    cases.append(("200_and_503", ..., False))
    # 403 + 404 mixed → True (both 4xx)
    cases.append(("403_and_404", ..., True))
    results = []
    for name, results_list, expected in cases:
        actual = _static_results_are_uniformly_dead(results_list)
        results.append((name, actual == expected, f"expected={expected} actual={actual}"))
    return results

if __name__ == "__main__":
    for n, ok, m in run():
        print(f"{'PASS' if ok else 'FAIL'}  {n}  {m}")
```

### 5. 회귀 — 살아있는 URL 영향 확인

`python scripts/probe_smoke.py --stage 3 --stage 5` 통과 의무. 기존 21+ probe fixture 가 *살아있는* board URL 들이라 영향 0 이어야 함 (전부 200 OK).

### 6. 사후 검증 — 10 사이트 실측

본 task 끝나면 Claude 가 10 사이트 재시도 (`scripts/remote.py batch-register --catalog=2026-05-24-games-mobile-strategy-rpg --failed`). 새 게이트가 작동하면:
- 8 url_dead → rc=4 REJECTED (자동) + `.REJECTED.json` 박힘
- 2 anti-bot (castleclash) → rc=5 (진짜 cap_blocked) → auto Later

기대: 큐가 자동 정리. 수동 `_save_rejected` 호출 불요.

## case 작성

`docs/cases/_generic_probe_dead_static_skip.md` (generic improvement case):
- `outcome: improved` (C-layer probe heuristic 추가, batch 의 cross-site 8 사이트 + 미래 유사 사이트 cover)
- `fix_layer: C`
- `failure_keys: ["probe_phase2_oom_on_dead_url", "static_uniformly_dead_no_skip", "cap_blocked_false_positive"]`
- frontmatter Track B audit + 영향 trigger sites 명시 (batch 의 8 sites)
- ship evidence: 사용자 명시 ("등록 될 때 자동으로 되게 개선 — 수동 X")

## OUT OF SCOPE — 만지지 X

- `engine/strategies/` X (probe 영역만)
- `prompts/` X
- recognizer X
- configs/* X (이 task 는 site config 작성 0)

오직 `scripts/probe.py` + `tests/probe/test_dead_static_skip.py` + `docs/cases/_generic_probe_dead_static_skip.md` + (필요 시) `scripts/register.py` 의 4xx/5xx → rc=4 분류 보강.

## 검증 체크리스트

1. `python -m py_compile scripts/probe.py` exit 0
2. `python tests/probe/test_dead_static_skip.py` 전 PASS
3. `python scripts/probe_smoke.py --stage 3 --stage 5` PASS (회귀 0)
4. 새 Phase 2 skip 메시지가 dead URL probe 에서 로그 됨 (예: dummy probe 하나 돌려 확인)

## 동시 진행 중인 다른 codex worktree

`codex-wt/orb-bypass-20260527_193903` (Farlight afkjourney ORB bypass — engine/strategies/playwright_html.py). 본 task 와 *겹침 0* (probe 영역 vs strategy 영역). 동시 진행 OK.

Claude 는 양쪽 result 검토 후 직렬 merge 예정.
