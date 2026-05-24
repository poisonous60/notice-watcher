---
slug: host_dotnetrocks-com_RSS_7682fe1a
url: https://www.dotnetrocks.com/RSS
status: ⚠ 추론 개선 적용 — 등록은 LLM key 0개로 escalated
outcome: improved
date: 2026-05-24
failure_keys: [posts_nonempty, rss_feed_urls]
fix_layer: C+A+D
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [podcast, rss, direct-feed, auto-recovery, escalated]
requested_by: batch
---

## 무엇이 일어났나

직접 RSS URL 인 `https://www.dotnetrocks.com/RSS` 가 이전 흐름에서 nav-only/sidebar 후보로 오판되어 `[FAIL] posts_nonempty` 또는 등록 거부로 샐 수 있는 유형이다.

## 픽스

- C: RSS/Atom 후보를 `list_candidates.rss_feed_urls` 로 노출한다.
- D: `scripts/register.py` 가 `feed_candidates` 의 `input-url-feed-*` 후보를 우선 backfill 하도록 해 direct feed URL 이 `/feed` 같은 body link 후보보다 앞에 오게 했다.
- A: config writer 가 direct feed URL 을 `list.url_template` 으로 그대로 쓰도록 규칙을 추가했다.

## 등록 검증 상태

`register.py --reuse-probe https://www.dotnetrocks.com/RSS` 는 더 이상 nav-only 거부에서 멈추지 않고 LLM 생성 단계까지 도달했다. 등록 완료는 LLM key 부재로 막혔다.

원문:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

현재 backfill 확인: `rss_feed_urls[0].url=https://www.dotnetrocks.com/RSS`.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS.
- `python scripts/register.py --reuse-probe https://www.dotnetrocks.com/RSS` FAIL, 원인은 LLM key 0개.
- 영향 범위: direct RSS URL 우선순위와 nav-only bypass. 기존 config 직접 변경 없음.
