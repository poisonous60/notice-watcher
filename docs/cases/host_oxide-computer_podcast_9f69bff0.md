---
slug: host_oxide-computer_podcast_9f69bff0
url: https://oxide.computer/podcast/rss.xml
status: ⚠ 추론 개선 적용 — 등록은 LLM key 0개로 escalated
outcome: improved
date: 2026-05-24
failure_keys: [article_body_len, audio_share_host]
fix_layer: C+A+D
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [podcast, rss, audio-share, transistor, auto-recovery, escalated]
requested_by: batch
---

## 무엇이 일어났나

기존 실패는 `[FAIL] article_body_len` 계열이다. podcast RSS 가 Transistor feed/player host 를 통해 노출되면 item link 또는 feed host 가 본문 페이지가 아니라 audio/share surface 를 가리킬 수 있어 본문 HTML fetch 를 hard requirement 로 두면 실패한다.

## 픽스

- C: `probe/extract.py` 가 `*.transistor.fm`, `libsyn.com`, `simplecast.com`, `art19.com`, `megaphone.fm`, `anchor.fm`, `podbean.com`, `podtrac.com` 계열 audio share/feed host 를 `list_candidates.audio_share_host_detected` 로 노출하고 `body_empty_likely=true` 로 연결한다.
- D: `scripts/register.py` 가 오래된 `--reuse-probe` artifact 에서도 audio share 신호를 backfill 한다.
- A: config writer 가 audio share host podcast RSS 에 대해 `article.body_empty_acceptable:true`, `article.skip_status:[200]`, `article.content:[]` 를 쓰도록 규칙을 추가했다.

## 등록 검증 상태

`register.py --reuse-probe https://oxide.computer/podcast/rss.xml` 는 LLM 생성 단계까지 도달했지만 등록 완료는 LLM key 부재로 막혔다.

원문:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

현재 backfill 확인: `audio_share_host_detected.host=feeds.transistor.fm`, `body_empty_likely=true`.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS.
- `python scripts/register.py --reuse-probe https://oxide.computer/podcast/rss.xml` FAIL, 원인은 LLM key 0개.
- 영향 범위: podcast RSS audio-share body skip 신호. 기존 config 직접 변경 없음.
