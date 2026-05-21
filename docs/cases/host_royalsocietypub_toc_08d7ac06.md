---
slug: host_royalsocietypub_toc_08d7ac06
url: https://royalsocietypublishing.org/toc/rsta/current
status: ⚪ no change — Cloudflare managed challenge blocks current TOC
outcome: no_change
date: 2026-05-21
fix_layer: none
failure_keys: [capability_blocked, anti_bot_challenge]
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [publishers, academic-journals, toc, cloudflare, capability-blocked, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

Royal Society Publishing current TOC는 URL 성격상 board/list에 해당하지만, `playwright_html` + 현재 stealth로 렌더하면 실제 TOC가 아니라 Cloudflare 보안 확인 페이지만 반환한다.

## 근거

- URL: `https://royalsocietypublishing.org/toc/rsta/current`
- 렌더 결과: HTTP 403, title `잠시만 기다리십시오…`
- body text: `royalsocietypublishing.org 보안 확인 수행 중 ... 악의적인 봇으로부터 보호 ... Ray ID ... Cloudflare`
- 실제 TOC row selector 후보는 0건

## 결정

config를 만들지 않았다. 이 케이스는 board-ness는 맞지만 capability_blocked다.

## 검증

- live render 1회 확인: Cloudflare challenge 고정
- `playwright_html` config 없음

## 트랙 B / 후속

일반화 후보 없음. current TOC selector를 작성할 HTML을 얻지 못했다.
