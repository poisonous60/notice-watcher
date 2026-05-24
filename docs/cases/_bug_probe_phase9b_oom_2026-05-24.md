---
slug: _bug_probe_phase9b_oom_2026-05-24
url: https://www.podcastindex.org/
status: ✅ 1차 방어선 — probe RSS self-guard + systemd MemoryMax. root-cause(tracemalloc 정확 leak 지점) 별도 위임.
outcome: improved
date: 2026-05-24
fix_layer: F
failure_keys: [oom_kill, probe_memory_blowup, playwright_phase9b, capability_blocked]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/probe.py, scripts/register.py, bot/fail_taxonomy.py, tests/fail_taxonomy/test_classify_fail.py, deploy/notice-bot.service]
tags: [bugfix, probe, playwright, oom, memory, capability_blocked, batch-2026-05-21-podcast]
---

## 무엇이 일어났나

`2026-05-21-podcast` batch 의 `https://www.podcastindex.org/` 등록이 봇 worker 를 3번 죽였다
(`.BUG.json` rc=-5, "봇이 2회 처리 중 죽음"). systemd journal 동시 시각:

```
May 24 19:40:40 systemd[1879]: notice-bot.service: The kernel OOM killer killed some processes in this unit.
May 24 19:41:52 systemd[1879]: notice-bot.service: Failed with result 'oom-kill'.
```

kernel 이 single python process 를 죽였다 — `anon-rss:7510736kB` (7.5GB) / `total-vm:10517784kB`.
N100 = 12GB RAM, swap 0. 시스템 baseline ~5GB + 이 process 7.5GB = kernel global OOM (다른
service 인 `tailscaled` 도 victim 후보로 잡힐 뻔).

## root-cause (영역 확정, 정확 leak 지점 별도)

`mem_probe.py` 래퍼 (probe subprocess RSS 1초 폴링) 로 **단독 재현**:

```
[mem-probe] + 18.0s  total=  295MB
[mem-probe] + 40.0s  total= 3474MB  ← +1.7GB / 2s 점프
[mem-probe] + 54.0s  total= 7511MB  ← SIGKILL 영역 (rc=-9)
[PHASE log] [Phase 9b] article-by-click probe ...
```

영역 = **`probe/fetch_headless.py:fetch_article_by_click` (Phase 9b)** = 목록에서 글 링크 클릭
→ 최종 페이지·HAR 캡처. concurrency 아님, **단일 사이트 단독 실행도 폭주**. 같은 wrapper 로 다른
사이트 (`productthinking.cc/podcast`) 도 돌렸는데 Phase 9b 통과 후 peak 217MB — heavy SPA 만
trigger.

가설 (별도 tracemalloc 위임으로 확정):
- Phase 9b 는 의도적으로 stylesheet 차단 X (line 597 — 클릭 visibility 검출 목적)
- record_har_content="attach" 가 *대부분* 디스크 분리하지만 heavy SPA detail page navigate 시
  playwright Python sync API 가 response body / page state 를 메모리에 buffer
- 누적은 *python* process RSS 에 잡힘 (chromium 은 별도 PID — 그쪽이 아님)

## fix — 1차 방어선 2개 + root-cause 후속

### 1) `scripts/probe.py:_start_memory_guard` — RSS watchdog

probe 프로세스 daemon thread 가 `/proc/self/status` VmRSS 1s 폴링. `PROBE_MEMORY_GUARD_MB`
(default 3500) 초과 시 `os._exit(99)`. N100 12GB - 5GB baseline = 7GB 여유의 50% 선. concurrency
5 정상 case (각 ~200MB) 와는 충돌 X, 폭주 case 만 차단. Linux only (`/proc/self/status` 존재
검사 후 silently skip on Windows/macOS dev box).

### 2) `scripts/register.py:ProbeMemoryGuardError` — capability_blocked 분류

`_run_probe` 가 rc=99 잡으면 `ProbeMemoryGuardError` raise. caller 가 잡아 `_save_failed` +
`return 5` (capability_blocked 일치). anti-bot stealth 트랙 대상 X — 메모리 한계는 stealth 로
안 풀린다.

### 3) `bot/fail_taxonomy.py` — Subkind `probe_memory_guard` 추가

`capability_blocked` 안 새 Subkind. dashboard 분류 + 같은 패턴 재발 시 hint 표시. fixture
`tests/fail_taxonomy/test_classify_fail.py:CASES` + `docs/fail 분류.md` regen 동반 (`probe_smoke
--stage 5` 통과 확인).

### 4) `deploy/notice-bot.service:MemoryMax=10G` — cgroup 안전망

systemd cgroup limit. self-guard 가 *못 잡는* (예: native lxml allocation, threading race)
누적도 cgroup 이 받친다. 넘으면 kernel global OOM 대신 *이 service 만* OOM-kill 후 `Restart=on-failure`
재기동. **다른 system process (tailscaled 등) 보호**가 핵심. N100 live unit 도 `~/.config/systemd/user/notice-bot.service`
에 박음 + `daemon-reload` + `MemoryMax=10737418240` 확인.

### 5) (별도) tracemalloc 정확 leak 지점 — codex 위임

Phase 9b 안 어디서 python RSS 가 +1.7GB/2s 점프하나? 가설: HAR body buffer, page state, 또는
`page.evaluate(_LINK_JS)` 반환값. `tracemalloc.take_snapshot` 을 Phase 9b 진입·click·post-click
3 지점에 박아 *어느 framework call 이 누적의 owner 인지* 확정. 결과 다른 case 로.

## 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` exit 0 (configs 248/248 OK, fail_taxonomy
  971 cases PASS, fail 분류.md drift 0).
- `mem_probe.py` 재실행으로 podcastindex.org probe 가 **rc=99 self-kill** (peak ~3.5GB) 되어
  register 가 cleanly rc=5 + FAILED.json 박는지 확인은 N100 git pull + bot restart 후.

## 영향

같은 패턴 미래 사이트:
- *모든* heavy SPA probe 가 N100 service 를 죽이지 못함 (self-guard + cgroup 2중 방어).
- dashboard `/jobs` 에 `probe_memory_guard` Subkind 로 분류 — hand-config 워크플로가 capability
  한계로 즉시 인식.
- root-cause fix 가 박히면 (별도 case) 임계 낮추거나 Phase 9b 자체 개선 검토.
