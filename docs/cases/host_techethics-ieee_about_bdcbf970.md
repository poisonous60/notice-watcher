---
slug: host_techethics-ieee_about_bdcbf970
url: https://techethics.ieee.org/about/
status: ❌ 거부 (Cloudflare JA3 fingerprint 차단 + URL 이 단일 about 페이지)
outcome: rejected
date: 2026-05-16
fix_layer:
failure_keys: [cloudflare_ja3_block, headless_blocked, single_about_page]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [cloudflare, ja3-fingerprint, about-page, dual-blocker]
requested_by: 운영자 (dev box session)
---

## 무엇이 일어났나

`/watch https://techethics.ieee.org/about/` triage 큐 진입. probe 결과 모든 진입 전략이 403:

| 전략 | status | 비고 |
|---|---|---|
| S1.H2 (Chrome min UA) | 403 | server: cloudflare |
| S1.H3 (Chrome full headers) | 403 | sec-ch-ua + Sec-Fetch-* 포함 |
| S1.H4 (Chrome + Referer) | 403 | |
| S1.Hcap (Playwright 캡처 헤더 재주입) | 403 | |
| S4 (Playwright headless full) | 403 | har 캡처 됐는데도 |
| B1 (/) baseline | 403 | |
| B2 (robots.txt) | 200 | 193 bytes 정상 |

verdict: `CLOUDFLARE_PROTECTED_SITE`

dev box (N100) 에서 동일 UA 로 curl 시도 → **HTTP/2 200**. 즉:
- 헤더 차이가 원인 X (Chrome full UA + 동일 헤더 셋 다 줘도 httpx 만 403)
- IP 차단 X (curl 통과)
- 결론: **TLS handshake fingerprint (JA3/JA4) 기반 차단**. httpx 와 Playwright headless Chromium 의 TLS stack 이 진짜 Chrome 과 미세하게 달라 Cloudflare bot-management 가 거름. curl 의 TLS 는 별도로 분류돼 통과.

추가로 URL `/about/` 는 *프로그램 소개 정적 페이지* — 공지 list 자체가 아님. 차단 뚫어도 board 인식 단계에서 거부 예정.

## 왜 거부인가

두 가지 독립 차단 사유 동시:

1. **TLS fingerprint 차단** — `docs/차단 우회 기술 조사 (TLS fingerprint, DPI).md` 참고. `curl_cffi` 같은 impersonate 라이브러리 도입하면 가능하지만 의존성 + 유지보수 비용 크고 ToS 회색지대. 본 프로젝트 정책 (`docs/크롤링 지침.md`) = 우회 X.
2. **단일 about 페이지** — list 가 아니므로 인식기 자체가 거부할 URL. 사용자가 *원하는* 게 IEEE Tech Ethics 의 새 publication/news 라면 `https://techethics.ieee.org/publications/` 등 list 페이지로 다시 시도해야 함 (그것도 Cloudflare 막혀 있을 가능성).

## 픽스 (fix_layer: 없음)

코드 변경 X — 정책 거부. 단 진단 중 발견한 probe classifier 결함 2건은 별도 [[infra_probe_baseline_classifier_2026-05-16]] case 로 분리해서 처리 (robots.txt 짧은 본문 오분류, cert 에러 verdict 분리).

## 영향

- 자동 차단 가능 X — 이 사이트만 위해 `curl_cffi` 도입은 over-engineering.
- 같은 패턴 (Cloudflare JA3 차단 + about/single page) 들어와도 register 가 verdict `CLOUDFLARE_PROTECTED_SITE` 로 일관되게 거부.

## 회귀 검증

해당 없음 — 코드 변경 X. 위 infra case 의 회귀 검증으로 대체.

## 남은 정리

- 사용자가 IEEE Tech Ethics 의 *공지* 가 필요하면 list URL 다시 받기. 받아도 같은 Cloudflare 인프라면 또 막힘 — 그땐 [[infra_probe_baseline_classifier_2026-05-16]] 의 verdict 메시지로 명확히 거부 사유 전달.
- 트랙 B (probe 일반화) 후보: TLS fingerprint impersonation 도입 검토 — 별도 큰 인프라 작업, 본 case 범위 밖.
