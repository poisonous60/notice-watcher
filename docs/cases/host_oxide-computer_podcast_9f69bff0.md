---
slug: host_oxide-computer_podcast_9f69bff0
url: https://oxide.computer/podcast/rss.xml
status: ✅ 자동생성 성공 (옵션 A site_kind=hybrid med — N100 register 시도 2 PASS 30건). handcrafted config 도 보존
outcome: improved
date: 2026-05-25
failure_keys: [article_body_len, audio_share_host]
fix_layer: C+A+D+F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/digest.py, scripts/register.py, probe/extract.py, prompts/config_writer.system.txt]
tags: [podcast, rss, audio-share, transistor, auto-recovery, site-kind-proof]
requested_by: batch
---

## 2026-05-25 갱신 — 옵션 A site_kind enum 효과 입증

청크 F2 (commit `04817bf`) + 직접 fix (`af41a2e`/`e638bfe`/`8610d9c`) + 청크 G (`<TBD>`) 박힌 후 N100 register --reuse-probe --force 시도 결과:

- site_kind: `hybrid med` evidence=`[rss_feed_urls:link_rel, html_same_host_rows:5, audio_share:host_known]`
- primary_feed_url: `https://feeds.transistor.fm/oxide-and-friends` (list.html 의 `<link rel="alternate" type="application/rss+xml">` 에서 추출)
- 자동생성 결과: 시도 1 fail / **시도 2 PASS** — strategy=httpx_html, url_template=feeds.transistor.fm/oxide-and-friends, row_selector="rss > channel > item", article.body_empty_acceptable=true skip_status=[200]
- N100 baseline 30건 등록 ✅

= **handcrafted config 없이 자동생성 가능 확인**. handcrafted (커밋 `4f3fbc7`) 와 동등 결과 — site_kind=hybrid med 의 prompt hint 효과로 LLM 이 link rel primary 사용 + audio_share host_known 기존 룰로 body skip.

handcrafted config 는 *fallback* 으로 보존 (운영 안정성). 다음 batch 의 같은 패턴 site 는 자동생성으로 처리 기대.


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
