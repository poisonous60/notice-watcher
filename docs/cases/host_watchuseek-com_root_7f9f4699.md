---
slug: host_watchuseek-com_root_7f9f4699
url: https://www.watchuseek.com/
status: 🐛 BUG 방어 — SIGBUS subprocess death 를 gen_fail 로 오분류하지 않고 BUG 경로로 보냄
outcome: improved
date: 2026-05-21
fix_layer: F
failure_keys: [subprocess_signal, sigbus, headless_dom_pressure, xenforo_rss]
config_strategy: none
adapters_changed: []
engine_files_touched: [bot/site_ops.py, probe/fetch_headless.py]
tags: [bug, sigbus, chromium, playwright, xenforo, watchuseek, batch-2026-05-21-fedi]
requested_by: poisonous60
---

## 무엇이 일어났나

`2026-05-21-fedi` batch 에서 `register.py` subprocess 가 `proc.wait() == -7` 로 종료됐다.
Linux 에서 `-7` 은 signal 7, `SIGBUS` 이다. 기존 `bot/site_ops.py:blocking_register`
는 이 값을 그대로 worker 에 넘겼고, worker 는 `-1/-2/-3` 만 BUG 로 분류하므로 `-7` 이
일반 자동등록 실패처럼 triage 로 흘러갈 수 있었다.

그 결과는 잘못된 큐 오염이다. SIGBUS 는 사이트 config 생성 실패가 아니라 Chromium/Playwright
또는 subprocess 의 시스템 측 비정상 종료다.

## 원인

1. `site_ops` 가 signal death 를 정규화하지 않았다.
   - timeout 은 `-2`, lock/예외는 `-1/-3` 으로 BUG 경로를 타지만, `proc.wait() < 0`
     인 signal 종료는 그대로 반환했다.
   - 따라서 `SIGBUS` 가 `.BUG.json` 대신 `.FAILED.json`/triage 성격으로 보일 수 있었다.

2. headless capture 가 전체 DOM을 `page.content()` 로 한 번에 Python 으로 직렬화했다.
   - 큰 SPA/무거운 DOM 에서 Chromium renderer 와 Python parent 양쪽 메모리를 동시에 밀어올린다.
   - N100 같은 작은 Linux box 에서는 renderer crash, Node driver death, SIGBUS/OOM 류가
     batch 중 표면화될 수 있다.

## Watchuseek 확인

Watchuseek 는 XenForo 계열이고 경량 경로는 전역 RSS:

`https://www.watchuseek.com/forums/-/index.rss`

이번 dev box 네트워크에서는 RSS 요청이 `406 Not Acceptable` 로 막혔고
`xf_is_suspected_bot=1` 쿠키가 내려왔다. 즉 여기서는 RSS 경량 확인도 사이트 edge 에서
봇 의심 처리된다. 그래도 SIGBUS 자체는 RSS selector 문제가 아니라 headless/subprocess
비정상 종료 처리 문제다.

## 픽스

- `probe/fetch_headless.py`
  - `page.content()` 직접 호출 대신 `document.documentElement.outerHTML.slice(...)` 기반
    bounded capture 를 사용한다.
  - 기본 상한은 `PROBE_HEADLESS_HTML_CHAR_LIMIT` 또는 2,000,000 chars.
  - truncation 이 발생하면 `notable` 에 `html_truncated` 를 남긴다.

- `bot/site_ops.py`
  - `proc.wait() < 0` 이면 signal death 로 보고 tail 에 signal 정보를 남긴다.
  - worker 의 기존 BUG 경로를 타도록 rc 를 `-3` 으로 정규화한다.
  - signal 종료 직후에도 process group kill 을 best-effort 로 한 번 더 호출해 손자 process
    잔류를 줄인다.

## 검증

- `python -m py_compile probe/fetch_headless.py bot/site_ops.py` PASS.
- `_capture_page_content` fake-page smoke PASS.
- `_wait_xhr_quiet` fake-page smoke PASS.
- `bot.site_ops._signal_name(-7)` smoke PASS (Windows dev box 에서는 `SIG7`, Linux 에서는
  `SIGBUS` 로 표기 예상).
- Watchuseek RSS curl: `406 Not Acceptable`, `xf_is_suspected_bot=1` 확인.

## 한계

- 이 변경은 Watchuseek 등록 성공을 보장하지 않는다. 현재 dev box 네트워크에서는 RSS도 edge
  차단된다.
- `engine/recognizers/xenforo.py`, `probe/extract.py`, `scripts/register.py` 는 이번
  HARD-STOP allow-list 밖이라 수정하지 않았다.
