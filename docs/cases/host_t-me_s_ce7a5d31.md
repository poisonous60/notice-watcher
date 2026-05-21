---
slug: host_t-me_s_ce7a5d31
url: https://t.me/s/durov
status: ✅ 등록 (Telegram public channel list-only)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [article_body_len, body_empty_acceptable, list_only]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [telegram, public-channel, list-only, batch-2026-05-21-misc]
---

## 무엇이 일어났나

자동 config 는 `https://t.me/s/durov` 목록에서 500~504 글의 `post_id`, title, url,
published_at 을 정상 추출했다. 실패는 article 단계에서만 발생했다:

`[FAIL] article_body_len: post_id=500 0자 (<100 — content selector 의심)`

직접 확인 결과 `https://t.me/durov/500` 은 embed/channel shell 이고
`.tgme_widget_message_text` 를 제공하지 않는다. 반면 목록 페이지 `https://t.me/s/durov` 의
row 안에는 메시지 텍스트가 들어 있어 알림 제목/요약에는 충분하다.

## 조치

`configs/host_t-me_s_ce7a5d31.json` 을 목록 기반 list-only config 로 작성했다.

- `row_selector: section.tgme_channel_history... > div.tgme_widget_message_wrap...`
- `post_id` 는 `data-post` 에서 숫자 추출
- `title`/`summary` 는 `.tgme_widget_message_text.js-message_text`
- `published_at` 은 message date `time[datetime]`
- `article.content: []`, `body_empty_acceptable: true`

## 검증

- config schema validation PASS.
- `register.py --config configs/host_t-me_s_ce7a5d31.json` PASS, baseline 19건.
- 본문 0자 경고는 의도된 list-only 동작이다.

## 트랙 B

Telegram public channel은 platform recognizer 후보지만, URL 형태 전체와 pagination/older messages
정책을 정하지 않은 상태에서 넓히면 과매칭 위험이 있다. 이번 요청 범위에서는 단일 config 로 고정했다.
