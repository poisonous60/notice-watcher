---
slug: host_cbs-co-kr_podcast_0c51c954
url: https://www.cbs.co.kr/podcast/
status: ⚠ 추론 개선 적용 — 등록은 LLM key 0개로 escalated
outcome: improved
date: 2026-05-24
failure_keys: [posts_nonempty, rss_feed_urls]
fix_layer: C+A+D
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [podcast, rss, auto-recovery, escalated]
requested_by: batch
---

## 무엇이 일어났나

podcast batch A 대상. 기존 실패는 `[FAIL] posts_nonempty` 계열이며, probe 에 feed 후보가 있었지만 config writer 가 실제 feed URL 대신 추측 URL 을 만들 수 있는 유형이다.

로컬 probe artifact 가 처음엔 없어서 지시된 예외 경로로 `python scripts/triage.py pull --slug ...` 를 실행했고, N100 output snapshot 을 dev box `output/` 으로 회수했다.

## 픽스

- C: `probe/extract.py` 가 HTML `<link rel=alternate type=application/rss+xml|atom+xml>`, body RSS/feed anchor, HAR XML feed response 를 `list_candidates.rss_feed_urls` 로 추출한다.
- D: `scripts/register.py` 가 오래된 `--reuse-probe` artifact 에서도 `rss_feed_urls` 를 digest 에 backfill 한다.
- A: `prompts/config_writer.system.txt` 에 `rss_feed_urls[0].url` 을 `list.url_template` 으로 그대로 쓰라는 규칙을 추가했다.

## 등록 검증 상태

`register.py --reuse-probe https://www.cbs.co.kr/podcast/` 는 digest 생성과 feed 기반 등록 진행 조건까지 도달했지만 LLM 호출 환경에서 멈췄다.

원문:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

현재 backfill 확인: `rss_feed_urls[0].url=https://www.cbs.co.kr/rss`.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 5` PASS.
- `python scripts/register.py --reuse-probe https://www.cbs.co.kr/podcast/` FAIL, 원인은 LLM key 0개.
- 영향 범위: RSS feed URL 신호 추가와 prompt 규칙 추가. 기존 config 직접 변경 없음.
