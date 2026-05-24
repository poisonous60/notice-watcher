# podcast batch A result

## A/B/C fixes

- A RSS feed URL discovery: added `list_candidates.rss_feed_urls` extraction from link-rel, HTML body feed/rss anchors, and HAR XML feed responses. Prompt now says to use `rss_feed_urls[0].url` as `list.url_template` without guessing.
- B RSS post_id: prompt now says to avoid unstable long/URL-like RSS `guid` values and prefer `link` path tail with `regex_extract "/([^/?#]+)/?$"`.
- C podcast audio-share body skip: added `audio_share_host_detected` for Transistor/Libsyn/Simplecast/ART19/Megaphone/Anchor/Podbean/Podtrac style podcast hosts, sets `body_empty_likely`, and prompt now asks for `body_empty_acceptable:true`, `skip_status:[200]`, `content:[]`.

## Slug outcomes

- `host_cbs-co-kr_podcast_0c51c954`: escalated. `rss_feed_urls[0].url=https://www.cbs.co.kr/rss`; `register.py --reuse-probe` reached LLM generation but failed because Gemini keys are unavailable.
- `host_dotnetrocks-com_RSS_7682fe1a`: escalated. Direct feed URL now wins: `rss_feed_urls[0].url=https://www.dotnetrocks.com/RSS`; nav-only reject no longer blocks it. LLM generation failed because Gemini keys are unavailable.
- `host_feeds-thisameri_talpodcast_c725ed7a`: escalated. Prompt fix for RSS post_id is in place and direct feed URL backfills. LLM generation failed because Gemini keys are unavailable.
- `host_oxide-computer_podcast_9f69bff0`: escalated. `audio_share_host_detected.host=feeds.transistor.fm`, `body_empty_likely=true`; LLM generation failed because Gemini keys are unavailable.

## Escalate

All 4 registration checks are blocked by the same environment issue:

```text
LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.
```

No handcrafted configs were created.

## Verification

- `python scripts/triage.py pull --slug ...` succeeded and restored local `output/probe` artifacts.
- `python scripts/probe_smoke.py --stage 5` PASS.
- `register.py --reuse-probe` was run for all 4 URLs; all reached LLM generation or later and failed on Gemini key availability.
