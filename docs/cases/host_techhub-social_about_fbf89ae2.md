---
slug: host_techhub-social_about_fbf89ae2
url: https://techhub.social/about
status: social platform detect-reject
outcome: improved
date: 2026-05-21
fix_layer: C
failure_keys: [posts_nonempty, article_body_len]
config_strategy: rejected
engine_files_touched: [probe/extract.py, scripts/probe.py, scripts/register.py, probe/_contract.py]
tags: [mastodon, fediverse, social-reject, detect-reject, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`https://techhub.social/about` 는 Mastodon app shell 이다. 정적 HTML 은 `head > link`, `head > meta`
같은 반복 후보만 제공하고, notice board 로 볼 글 목록이나 첫 글 URL 은 없다.

핵심 marker:

- `<div id="mastodon">`
- `initial-state` JSON 의 `"meta":{"streaming_api": ...}`
- `<noscript>` 안 Mastodon 안내

이 페이지를 generic config 생성으로 보내면 `posts_nonempty: 0건` / `article_body_len` 실패가 난다. 그러나
Mastodon/Misskey/Pixelfed root/about 은 공지 게시판이 아니라 social timeline/client shell 이므로 수동 config 대상도 아니다.

## 무엇을 바꿨나

### 1. `probe/extract.py`

- `detect_mastodon_platform`
- `detect_misskey_platform`
- `detect_pixelfed_platform`

세 휴리스틱을 추가했다. 모두 URL 만으로는 판정하지 않고 HTML app-shell marker 가 있을 때만
`{"is_<platform>": true, "base_url": ...}` 를 산출한다.

### 2. `scripts/probe.py` + `probe/_contract.py`

`list_candidates.json` 에 `mastodon_platform`, `misskey_platform`, `pixelfed_platform` 키를 추가했다.
contract note 에 이 키들은 platform config dispatch 가 아니라 detect-reject 용도임을 명시했다.

### 3. `scripts/register.py`

Lemmy/PeerTube/Mbin positive dispatch 는 유지하고, board-shape/nav gate 전에 social detect-reject 를 추가했다.

해당 신호가 있으면:

- `.REJECTED.json` 저장
- `learn=False`
- rc=3 반환
- Gemini config 생성 호출 없음

## Lemmy rc=5 API rescue

같은 변경에서 Lemmy HTML UI 가 anti-bot/captcha 로 막혀 `_policy_check` 가 rc=5 로 갈 때만 마지막으로
`GET <base>/api/v3/site` 를 확인한다. `site_view` 또는 `version` 이 보이면 `engine.recognizers.lemmy.build_config(base)`
로 LemmyAdapter config 등록을 시도한다. 실패하면 기존 rc=5 FAILED 흐름을 그대로 유지한다.

게이트 순서는 바꾸지 않았다. `_policy_check` 이후 rc=5 반환 직전에만 rescue 를 시도한다.

## 검증 포인트

- Mastodon/Misskey/Pixelfed marker fixture 는 detect 된다.
- 일반 notice board fixture 에 `Mastodon`/`Misskey` 문자열이 있어도 detect 되지 않는다.
- social root/about URL 은 URL-only recognizer 로 매칭되지 않는다.
- social detect 신호는 `_save_rejected(..., learn=False)` + rc=3 으로 dispatch 된다.
- Lemmy rc=5 rescue 는 `/api/v3/site` JSON 이 Lemmy 로 보일 때만 LemmyAdapter 등록을 호출한다.

## 트랙 B 검토

- (2a) 플랫폼 config — 적용 X. social instance 는 게시판 플랫폼이 아니라 reject 대상이다.
- (2b) `--article-url` 재시도 — 적용 X. 첫 글 URL 문제가 아니라 페이지 성격이 notice board 가 아니다.
- (2c) probe 휴리스틱 — 적용. HTML marker 를 구조 신호로 산출해 generic 생성 전에 종료한다.
- (2d) probe 오작동 — 적용 X. probe 는 app shell 을 정상 수집했다.
- (2e) 수동 config — 적용 X. firehose/social client shell 은 폴링할 notice board 가 아니다.
