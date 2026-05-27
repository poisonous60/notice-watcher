---
slug: _generic_atom_tag_uri_stable_id
url: ""
status: "✅ improved (atom RFC 4151 tag URI 수용)"
outcome: improved
fix_layer: F
failure_keys:
  - stable_id_shape_atom_tag_uri
  - broken_recover_zombie_cb
trigger_slug: host_status-deno-com_root_5aa73944
config_strategy: httpx_html
engine_files_touched:
  - generate/validate.py
  - scripts/poll.py
  - scripts/remote.py
  - scripts/replay.py
tags:
  - atom
  - rfc4151
  - tag-uri
  - stable_id
  - broken_recover
date: 2026-05-27
---

## 문제

BROKEN 큐 복구 작업 중 `host_status-deno-com_root_5aa73944` 가 manual poll 에서 즉시 다시 깨졌다.

```
=== host_status-deno-com_root_5aa73944 ===  https://status.deno.com/history.atom [httpx_html]
  ⚠ 깨짐 신호 #10: post_id 모양 이상(공백 등): ['tag:denostatus.com,2005:Incident/cmovrz1s7065icessbsqvfgl3', …]
  ❗ BROKEN sidecar 박음 (cb=10 ≥ 3)
```

fetch_list 자체는 정상 (26 entries 반환). 모든 post_id 가 [RFC 4151](https://www.rfc-editor.org/rfc/rfc4151) atom tag URI 형식: `tag:authority,YYYY:specific`. `,` 가 날짜 구분자.

`scripts/poll.py:_looks_broken` 의 `_STABLE_ID_RE = ^[\w\-./:%]{1,200}$` 가 `,` 거부 → 모든 post_id `bad_id` 분류 → `broken=True` → cb 누적 zombie loop.

## 근본 원인

`_STABLE_ID_RE` 문자집합이 RFC 4151 표준을 안 받았다. Atom feed 표준 id (`<entry><id>tag:...</id>`) 의 `,` 가 빠짐. statuspage.io / GitHub atom 등 atom 표준 feed 전체가 같은 패턴 — generic.

같은 정규식 4 곳 동기화 필요:
- `generate/validate.py:24` — register-time post_id 검증
- `scripts/poll.py:75` — poll-time `_looks_broken`
- `scripts/remote.py:69` — CLI 인자 validation
- `scripts/replay.py:170` — replay inline regex

## 픽스 (F-layer)

문자집합에 `,` 추가:

```python
_STABLE_ID_RE = re.compile(r"^[\w\-./:%,]{1,200}$")
```

공백 거부 (title 오인) · 길이 cap (200 / 128) 그대로. `,` 만 확장 — 비파괴.

테스트 추가 (`tests/validate/test_post_id_stable_shape.py`):
- `atom_tag_uri_statuspage`: `tag:denostatus.com,2005:Incident/cmovrz1s7065icessbsqvfgl3` → accept
- `atom_tag_uri_github_style`: `tag:github.com,2008:Repository/12345/abcdef0123456789` → accept

## 영향 사이트

직접: `host_status-deno-com_root_5aa73944` (deno status atom).

잠재: 모든 statuspage.io clone atom feed (Cloudflare, GitHub, Stripe, Discord 등 수많은 SaaS) + atom 표준 준수 RSS feed. 등록 시점에는 register 가 어떻게든 통과시켰지만 (정확한 경로 미조사 — `_STABLE_ID_RE` hard check 임에도 통과한 history 가 jobs rc=0 로 다수 존재) poll 의 `_looks_broken` 이 같은 정규식으로 reject 해 zombie cb 누적.

## 검증

- `tests/validate/test_post_id_stable_shape.py` — atom_tag_uri 2 fixture 추가, probe_smoke stage 5 PASS.
- `python scripts/probe_smoke.py` → PASS 1730 / FAIL 0 / WARN 1 (기존 unrelated worker warning).
- N100 deploy 후 manual poll: `host_status-deno-com_root_5aa73944` 가 정상 복구 (cb=0 + BROKEN sidecar unlink) 예정.

## 같은 batch 동료 slug (BROKEN 큐 4건)

| slug | live | 결과 |
|---|---|---|
| host_status-deno-com_root_5aa73944 | atom 200 (302 → denostatus.com) | 본 F-layer fix 으로 회복 |
| host_cdjapan-co-jp_feature_ba56403b | 200 OK | manual poll 으로 회복 (cb 6→0, BROKEN unlinked) |
| host_news-blizzard-c_en-us_ef8e0474 | /api/news 500 (5일+ 연속 upstream outage) | REJECTED capability_blocked — 별도 |
| host_techradar-com_root_8baaf5b7 | 200 OK | manual poll 으로 회복 (cb 6→0, BROKEN unlinked) |

## fix_layer 분류

F (engine validator code change). `_STABLE_ID_RE` 자체가 schema-ish (E 후보) 지만 `engine/config_schema.py` 가 아닌 `generate/validate.py` 의 runtime validator → F. CNN 130자 cap case (`host_edition-cnn-com_world_ae74b4db.md`) 와 동형.

## outcome 분류

improved (mechanism = generic 추론 개선 — atom RFC 4151 표준 받는 정규식 확장). 단일 사이트 config 손 X. 미래 atom feed 전체 자동 처리.
