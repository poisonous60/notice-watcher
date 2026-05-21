---
slug: host_journals-sagepu_action_5a296461
url: https://journals.sagepub.com/action/showPublications
status: ⚪ no change — Cloudflare managed challenge blocks playwright_html
outcome: no_change
date: 2026-05-21
fix_layer: none
failure_keys: [capability_blocked, anti_bot_challenge]
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [publishers, academic-journals, cloudflare, capability-blocked, batch-2026-05-21-publishers]
---

## 무엇이 일어났나

SAGE Publications journal directory는 `playwright_html` + 현재 stealth로 렌더했지만 실제 publication rows가 아니라 Cloudflare 보안 확인 페이지만 반환했다.

## 근거

- URL: `https://journals.sagepub.com/action/showPublications`
- 렌더 결과: HTTP 403, title `잠시만 기다리십시오…`
- body text: `journals.sagepub.com 보안 확인 수행 중 ... 악의적인 봇으로부터 보호 ... Ray ID ... Cloudflare`
- 실제 publication row selector 후보는 0건

## 결정

config를 만들지 않았다. interactive captcha/Turnstile/managed challenge를 자동으로 풀거나 우회하는 것은 이번 track A 범위 밖이다.

## 검증

- live render 1회 확인: Cloudflare challenge 고정
- `playwright_html` config 없음

## 트랙 B / 후속

일반화 후보 없음. 현재 `playwright_html` 능력으로는 통과하지 못하는 capability_blocked 케이스다.
