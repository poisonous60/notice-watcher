---
slug: host_france24-com_en_a8047c17
url: https://www.france24.com/en/
status: 🚫 보류 (anti-bot 403 capability_blocked; stealth 우회 구현 안 함)
outcome: rejected_with_policy
date: 2026-05-21
fix_layer: none
failure_keys: [capability_blocked, fetch_list]
config_strategy: none
tags: [france24, anti-bot, http-403, capability-blocked, batch-2026-05-21-blogcms-gen3]
---

## 원인

`httpx_html` config 시도는 `HTTPStatusError: 403 Forbidden`으로 실패했다. Probe digest는 `JS 실행 필요 (Cloudflare 등)`과 Playwright/stealth 계열을 추천했지만, 이번 task의 hard-stop은 stealth/anti-detection 어댑터 구현을 금지한다.

## 처리

- config 생성 안 함.
- `output/poll_state/host_france24-com_en_a8047c17.FAILED.json`을 `capability_blocked` 성격으로 갱신했다.
- 우회/전용 adapter 작업은 보류했다. 정책상 stealth 우회 구현은 별도 명시가 있을 때만 검토한다.

## 회귀 검증

- 기존 artifact 확인: `output/probe/host_france24-com_en_a8047c17/list.html`에는 글 목록 신호가 있으나, 실제 httpx fetch가 403으로 차단된다.
- 영향 0개: config/engine/recognizer 변경 없음.

## 트랙 B

capability_blocked/403 누적 사례는 이미 많지만, 해결은 새 우회 capability 또는 site-specific adapter가 필요하다. 이번 allow-list와 정책 범위에서는 일반화 작업을 하지 않았다.
