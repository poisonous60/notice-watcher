---
slug: host_booth-pm_announcements_b96f82ef
url: https://booth.pm/announcements
status: ✅ 손 config 등록 (baseline 20건, httpx_html)
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [probe_timeout]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [booth, announcements, static-html, probe-timeout]
---

## 무엇이 일어났나

`register.py` 가 probe 단계에서 120초 timeout 으로 실패했다.

`preflight: b-hit — host_booth-pm_announcements_b96f82ef [27ed350, 5665fa8]`.
실패 이후 영향 영역 commit 이 있어 `python scripts/register.py --reuse-probe "https://booth.pm/announcements"` 를 먼저 실행했지만, 저장된 probe 산출물이 digest 까지 완성되지 않아 다시 lite probe 로 들어가 timeout 났다.

캡처된 `s1.H2.html` 자체에는 공지 목록이 정적으로 들어 있었다. 실제 row 는 `div.list > a.legacy-list-item.nav[href^='/announcements/']`, 글 본문도 개별 공지 페이지의 `.l-announcement-body` 에 정적으로 들어 있다.

## 무엇을 바꿨나

`configs/host_booth-pm_announcements_b96f82ef.json` 을 추가했다.

- 목록: `https://booth.pm/announcements`
- row: `div.list > a.legacy-list-item.nav[href^='/announcements/']`
- post_id: `/announcements/<id>`
- 날짜: `YYYY年M月D日` → `%Y-%m-%d` → `+09:00`
- 본문: `.l-announcement-body`

## Track B 검토

새 probe/schema/prompt/recognizer 변경은 하지 않았다. 이 케이스는 일반적인 정적 HTML 목록과 본문을 기존 `httpx_html` 어휘로 처리할 수 있고, 실패 원인은 selector 추론 실패가 아니라 probe timeout 이었다.

BOOTH 전체 플랫폼 recognizer 도 보류했다. 현재 입력은 단일 공지 board 이고, 같은 URL 패턴의 추가 BOOTH board 사례가 없어 플랫폼화하면 과한 변경이다.

## 회귀 검증

- `python scripts/register.py --config configs/host_booth-pm_announcements_b96f82ef.json` → PASS, baseline 20건.
- `make_adapter` 손 실행 → list 5건, 첫 글 body 744 chars.
- 영향 범위: 새 엔진/프롬프트/recognizer 변경 없음. 단일 config 1건만 추가.
