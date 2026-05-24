---
slug: host_feeds-thisameri_talpodcast_c725ed7a
url: https://feeds.thisamericanlife.org/talpodcast
status: ⚠ 프롬프트 개선 적용 — 등록은 LLM key 0개로 escalated
outcome: improved
date: 2026-05-24
failure_keys: [post_id_stable_shape, rss_post_id]
fix_layer: A
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [podcast, rss, post-id, auto-recovery, escalated]
requested_by: batch
---

## 무엇이 일어났나

기존 실패는 `[FAIL] post_id_stable_shape` 계열이다. RSS item 의 `<guid>` 가 긴 원문/URL 조합이면 post_id 로 부적합하고, `link` path tail 이 더 안정적인 fallback 이다.

## 픽스

- A: `prompts/config_writer.system.txt` 에 RSS item `<guid>` 가 긴 문장/URL/복합 문자열이면 `link` path tail 을 `regex_extract "/([^/?#]+)/?$"` 로 post_id 에 쓰라는 규칙을 추가했다.
- C/D: 오래된 artifact 에서 direct feed URL 을 `rss_feed_urls` 로 backfill 해 direct feed 입력도 feed config 작성 경로로 들어가게 했다.

## 등록 검증 상태

`register.py --reuse-probe https://feeds.thisamericanlife.org/talpodcast` 는 LLM 생성 단계까지 도달했지만 등록 완료는 LLM key 부재로 막혔다.

원문:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

현재 backfill 확인: `rss_feed_urls[0].url=https://feeds.thisamericanlife.org/talpodcast`.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS.
- `python scripts/register.py --reuse-probe https://feeds.thisamericanlife.org/talpodcast` FAIL, 원인은 LLM key 0개.
- 영향 범위: RSS post_id 작성 규칙. 기존 config 직접 변경 없음.
