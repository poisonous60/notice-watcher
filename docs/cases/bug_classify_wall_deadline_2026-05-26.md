---
slug: bug_classify_wall_deadline_2026-05-26
url: (infra — no single url)
status: 🟢 fixed (회귀 0 — probe_smoke 1491 PASS)
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys:
  - register_wall_timeout
  - classify_llm_stall
tags:
  - bug
  - timeout
  - classifier
  - register
---

# `classify_index_content` LLM 호출이 register wall budget 무시 → 300s timeout (rc=-2)

## 증상

`batch-register --catalog=2026-05-24-games-crowdfund` 100 건 중 18 건이 `register.py 실행 시간
초과 (300s)` (rc=-2, .BUG.json) 으로 죽음. 모두 kickstarter/indiegogo/fig.co campaign 페이지.

bot.log stall 패턴:

```
12:39:48  register.py 시작
12:40:53  [register] digest 구성  ← 여기서 235초 침묵
12:44:48  register.py 종료: rc=-9 (타임아웃 kill)
```

probe 자체는 64s 에 정상 종료. stall = *digest 이후* `_classify_veto` → `classify_index_content`.

## root-cause

`generate/classify.py:classify_index_content` 는 register 의 `wall_deadline` 을 받지 않음:

- `_RETRY = 3`
- gemini client 기본 timeout = 120s (`generate/gemini.py:146`)
- 백오프 `time.sleep(2 * attempt)` = 2+4 = 6s
- 최악 = 3 × 120 + 6 = **366s** > register wall budget 300s

`scripts/register.py:_classify_veto`/`_gate_reject_or_veto`/`_accept_path_content_reject` 7 호출
자리 모두 `wall_deadline` 전파 안 함. register 의 `_remaining_budget`/`_ensure_budget`
체계와 단절.

## 수정 (F-layer, 2 files)

- `generate/classify.py`: `classify_index_content(..., wall_deadline=None)` 추가
  - per-attempt 직전 `_remaining_wall_budget` 체크 — 남은 시간 < 5s 면 LLM 호출 없이
    `{"class":"?","reason":"wall_deadline_exhausted: rem=Xs"}` 반환 (fail-safe).
  - per-attempt timeout = `min(remaining_budget, 60s)` 로 client 의 `timeout` 속성 임시 override
    (`_temporary_client_timeout` context manager — primary/fallback child 도 walk).
  - 백오프 `time.sleep` 도 남은 budget 으로 클램프.
- `scripts/register.py`: `_classify_veto`/`_gate_reject_or_veto`/`_accept_path_content_reject` 에
  `wall_deadline` kwarg 추가 + 7 호출 자리 전부 `wall_deadline=wall_deadline` 전달.
  `_CLASSIFY_VETO_CACHE` key 는 그대로 (deadline 은 key 에 포함 X — 같은 (digest,url,slug) 결과 재사용).

기본 `None` = 옛 동작 유지 (regression 0). register 의 `main()` 은 이미 `wall_deadline = time.monotonic()
+ args.wall_timeout` 변수 있음 — 그걸 전달.

## 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 1491 / FAIL 0
- 영향 사이트: classifier 호출하는 *모든* register 호출 — 회귀 표면 큼. probe_smoke unit + integration 1491
  모두 PASS = generic 추론 동작 동등.

## 영향

batch 의 timeout 18 건 + 미래 같은 패턴 (LLM API 일시 stall × N retry) 자동 차단. 18 건 자체는
재시도해 봐도 대부분 content/catalog 로 rc=3 거부될 가능성 높음 (kickstarter projects = single
campaign content) — *fix 의 본질 가치* = LLM stall 이 다른 site 의 wall budget 까지 먹지 않게.
