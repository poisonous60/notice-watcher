---
slug: host_feddit-de_root_584f7d0f
url: https://feddit.de/
status: "rc=5 capability_blocked target — Lemmy API rescue path generalized; endpoint currently not open from dev box"
outcome: improved
date: 2026-05-21
requested_by: batch
failure_keys: [capability_blocked, fediverse_api_rescue, lemmy_api_rescue]
fix_layer: F
config_strategy: handwritten
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [lemmy, fediverse, api-rescue, anti-bot, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`https://feddit.de/` 는 Lemmy 계열 root 로 triage 된 rc=5 capability_blocked 대상이다. HTML root 가 차단되더라도 Lemmy public API 가 열려 있으면 config 생성은 HTML scraping 대신 `LemmyAdapter` 로 처리하는 것이 더 작고 안정적이다.

이번 변경은 rc=5 저장 직전 helper 를 `_try_fediverse_api_rescue` 로 일반화하고, Lemmy `/api/v3/site` 확인 성공 시 기존 Lemmy builder 로 등록을 시도하게 유지했다.

## API 확인

dev box 에서 2026-05-21 확인한 현재 응답:

- `/api/v3/site` -> 404
- `/api/v3/post/list?type_=Local&sort=New&limit=10` -> 404

따라서 이 작업 중 실제 config 파일은 생성하지 않았다. API 가 열려 있는 instance 또는 시점에서는 rc=5 직전 rescue 로 등록되고, API 확인이 실패하면 기존 실패 마커 저장 경로로 폴백한다.

## 트랙 B

- 2a 인식기: root URL-only recognizer 는 false-positive 위험으로 유지하지 않는다.
- 2b `--article-url`: X. root HTML 차단/endpoint capability 문제다.
- 2c/F-layer: 적용. rc=5 API rescue 를 Lemmy/Mbin 공통 helper 로 정리했다.
- 2d probe 오작동: X. probe 신호 추가보다 API rescue 가 직접적이다.
- 2e 수동 config: X. 공개 API 미확인 상태라 config 작성은 하지 않았다.

## 검증

- `python -c "from tests.probe_heuristics import test_fediverse_api_rescue as t; print(t.run())"` -> Lemmy/Mbin rescue unit PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` -> PASS 841, FAIL 0

