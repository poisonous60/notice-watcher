---
slug: host_standardsuniver_e-magazine_0e5263ea
url: https://www.standardsuniversity.org/e-magazine/march-2017/ethics-and-technology/
status: ❌ 거부 (SSL cert hostname mismatch + 원본 URL 사라짐 — 302 다른 페이지)
outcome: rejected
date: 2026-05-16
fix_layer:
failure_keys: [ssl_cert_hostname_mismatch, dead_url_302_redirect, single_article_page]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [ssl-cert, dead-site, ieee-migration, single-article-page]
requested_by: 운영자 (dev box session)
---

## 무엇이 일어났나

`/watch https://www.standardsuniversity.org/e-magazine/march-2017/ethics-and-technology/` triage 큐 진입. probe 의 모든 baseline + 진입 전략이 SSL 에러:

| 전략 | error |
|---|---|
| B1, B2, S1.H2/H3/H4/Hcap (httpx) | `ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'www.standardsuniversity.org'. (_ssl.c:1032)` |
| S4 (Playwright) | `Page.goto: net::ERR_CERT_COMMON_NAME_INVALID` |

verdict (이전 코드): `BASELINE_BLOCKED` → register 메시지 "차단(BLOCKED) 사이트로 보임" (오해 소지).

cert 직접 조회:
```
subject: CN=*.ieee.org
SAN: *.ieee.org, *.standards.ieee.org, *.vtools.ieee.org, ieee.org
```
→ `*.standardsuniversity.org` 커버 X. IEEE 가 standardsuniversity.org 도메인을 standards.ieee.org 로 이관하면서 cert 갱신 누락.

`curl -k` (verify off) 결과:
```
HTTP/1.0 302 Moved Temporarily
Location: https://standards.ieee.org/about/training/
```
→ 원본 e-magazine 2017 글 자체가 죽었음. 모든 path 가 `standards.ieee.org/about/training/` 로 302.

사용자가 "브라우저는 잘 보인다" 한 건 cert 경고 클릭 통과 후 redirect 따라가서 *전혀 다른* 페이지 본 것.

## 왜 거부인가

1. cert hostname mismatch — 우회 (verify off) 는 정책 위반. + 우회해도 원본 URL 죽음.
2. URL 죽음 — 사이트 운영자가 redirect 로 모든 path 를 `/about/training/` 로 보냄. 사용자가 원한 *2017 ethics-and-technology 글* 자체가 존재 X. 봇이 redirect 따라가 등록해도 `/about/training/` 는 단일 페이지.
3. 트리플 차단 — cert + 죽은 URL + single page. 자동 등록 가능한 어떤 경로도 없음.

## 픽스 (fix_layer: 없음)

코드 변경 X — 정책 거부. 단 진단 중 발견한 probe classifier 결함 (cert 에러를 BASELINE_BLOCKED 로 뭉뚱그림) 은 별도 [[infra_probe_baseline_classifier_2026-05-16]] case 에서 해결. 새 verdict `CERT_OR_DNS_BROKEN` + register 메시지 분기 추가 → 본 case 와 동일 패턴이 다시 들어오면 사용자가 명확한 사유 받음.

## 영향

- 본 URL 등록 불가 — 사용자에게 *사이트가 사라졌다* 안내. (이전엔 "차단됐다" 로 잘못 안내했지만 infra fix 후 정정됨.)
- 같은 패턴 (운영자 cert 오설정 + dead URL) 들어오면 verdict 가 `CERT_OR_DNS_BROKEN` 으로 박혀 register 가 새 문구로 거부.

## 회귀 검증

해당 없음 — 코드 변경 X. infra case 회귀로 대체.

## 남은 정리

- 사용자가 IEEE Standards 의 *공지/소식* 이 필요하면 `https://standards.ieee.org/news-events/` 같은 살아있는 list URL 다시 요청 받기.
- 트랙 B (probe 일반화): 이 케이스에서 발견된 verdict 정밀화 = infra case 가 흡수. 본 case 차원의 일반화 X.
