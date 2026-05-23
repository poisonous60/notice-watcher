---
slug: _bug_diagnose_errno5_dns_marker
url: multiple
status: ✅ 개선 — DNS NXDOMAIN(`[Errno -5]`) 이 CERT_OR_DNS_BROKEN(rc=4 url_dead) 로 올바르게 분류됨
outcome: improved
date: 2026-05-23
fix_layer: C
failure_keys: [baseline_blocked_misclassify, dns_nxdomain_eai_nodata, errno_5_no_address]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/diagnose.py, tests/probe_heuristics/test_diagnose_cert_verdict.py]
tags: [bugfix, probe, diagnose, dns, classification, batch-2026-05-21-crypto]
---

## 무엇이 일어났나

`crypto` batch 의 6 사이트 (forum.aave.com / forum.curve.fi / forum.compound.finance /
forum.ens.domains / forum.1inch.io / forum.dydx.community) 가 N100 DNS 환경에서 NXDOMAIN
이지만 verdict 가 `BASELINE_BLOCKED` → rc=5 cap_blocked 로 잘못 분류돼 *stealth/render 트랙 후보*
처럼 보이게 됨. 실제로는 죽은 도메인이라 rc=4 url_dead 가 정답.

원인: `probe/diagnose.py:_CERT_OR_DNS_ERROR_MARKERS` 가 glibc `getaddrinfo(3)` 의 두 errno
(`-2` EAI_NONAME, `-3` EAI_AGAIN) 만 알고 있었음. N100 의 IPv4/IPv6 dual-stack 환경에서는
같은 NXDOMAIN 이 `-5` EAI_NODATA (`No address associated with hostname`) 로 떨어지는데 마커 누락 →
classifier 가 cert/dns 카테고리에 못 넣음 → `baseline_cert_broken=False` → verdict 가
`BASELINE_BLOCKED` (= anti-bot) 로 흘러감.

같은 batch 의 forum.lido.fi / forum.near.org 등 *다른* 사이트는 `-2` errno 가 떨어져서
올바르게 `CERT_OR_DNS_BROKEN` 으로 분류됨 — 같은 NXDOMAIN 이 환경에 따라 -2/-5 로 갈리는
glibc 동작 때문에 sporadic 이라 발견이 늦었다.

## 무엇을 바꿨나

`_CERT_OR_DNS_ERROR_MARKERS` 에 3 항목 추가:
- `[Errno -5]` — EAI_NODATA (IPv4/IPv6 dual-stack 환경의 NXDOMAIN)
- `No address associated with hostname` — `-5` 의 사람 읽는 메시지
- `ERR_NAME_NOT_RESOLVED` — Chromium/Playwright (`Page.goto`) 의 DNS 실패 형식

`tests/probe_heuristics/test_diagnose_cert_verdict.py` 에 2 회귀 케이스 추가
(`dns_eai_nodata_errno5`, `playwright_name_not_resolved`).

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS (936/936, +6 새 cases)
- 영향 사이트: 위 6개 — `remote.py batch-register --catalog=2026-05-21-crypto --failed` 재시도 시
  rc=5 → rc=4 reclassify 자동 회수.

## 일반화

휴리스틱 추가 X (이미 있는 marker 리스트 확장만). 다른 errno (-1/-4/-6/-7/-8) 는 NXDOMAIN
아닌 카테고리라 추가 안 함 — *발견된 실제 케이스* 만 박는다. 다음에 또 다른 errno 가 NXDOMAIN
으로 떨어지면 같은 자리에 한 줄.
