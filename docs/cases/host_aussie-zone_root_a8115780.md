---
slug: host_aussie-zone_root_a8115780
url: https://aussie.zone/
status: "rc=5 capability_blocked — Lemmy root HTML anti-bot; dev box API CF-403, 미등록 (rescue 인프라 일반화)"
outcome: no_change
date: 2026-05-21
requested_by: batch
failure_keys: [capability_blocked, fediverse_api_rescue, lemmy_api_rescue]
fix_layer: F
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [lemmy, fediverse, api-rescue, anti-bot, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`https://aussie.zone/` 는 Lemmy instance root다. HTML probe 경로가 anti-bot/capability blocked 로 끝나면 기존 `register.py` 는 rc=5 저장 직전에 Lemmy `/api/v3/site` 만 확인하는 rescue 를 시도했다.

이번 작업에서는 그 rescue 를 `_try_fediverse_api_rescue` 로 일반화했다. Lemmy 는 `/api/v3/site` 가 JSON site payload 를 반환하면 기존 `engine.recognizers.lemmy.build_config()` 로 `LemmyAdapter` config 등록을 시도한다.

## API 확인

dev box 에서 2026-05-21 확인한 현재 응답:

- `/api/v3/site` -> 403 Cloudflare HTML
- `/api/v3/post/list?type_=Local&sort=New&limit=10` -> 403 Cloudflare HTML

따라서 이 작업 중 실제 config 파일은 생성하지 않았다. API 가 열려 있는 실행 환경에서는 rc=5 직전 rescue 가 먼저 동작하고, API 도 막힌 환경에서는 기존처럼 `.FAILED.json` 로 남는다.

## 트랙 B

- 2a 인식기: root URL 은 URL-only recognizer 대상이 아니다. Lemmy false-positive 방지를 위해 probe marker/API rescue 경로만 사용한다.
- 2b `--article-url`: X. 첫 글 URL 문제가 아니라 root HTML 차단이다.
- 2c/F-layer: 적용. rc=5 직전 공개 fediverse API 확인과 config builder 재사용을 일반화했다.
- 2d probe 오작동: X. 추가 probe 없이 API capability 로 우회한다.
- 2e 수동 config: X. instance 하나짜리 config 보다 platform rescue 가 맞다.

## 검증

- `python -c "from tests.probe_heuristics import test_fediverse_api_rescue as t; print(t.run())"` -> Lemmy/Mbin rescue unit PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` -> PASS 841, FAIL 0

