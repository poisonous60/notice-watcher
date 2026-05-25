---
slug: _chunk-substack-rss-recovery
url: https://astralcodexten.substack.com/archive
status: ✅ Substack/RSS recovery chunk — direct Substack fast-path + short well-known feed validation
outcome: improved
date: 2026-05-25
failure_keys: [gate_reject, heterogeneous_hub, rss_available, spa_archive_shell]
fix_layer: C+F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/substack.py, probe/discover.py]
tags: [substack, rss, recognizer, probe-heuristic, chunk-3]
requested_by: chunk3-substack-rss-20260525
---

## 무엇이 일어났나

Substack archive/root pages can render as SPA shells with no static article rows. In that shape the probe digest has
`clean article cluster 0`, so the heterogeneous hub post-mortem can reject the URL even though the same origin exposes
a public RSS feed at `/feed`.

Local artifact note: this worktree did not contain `output/probe/host_astralcodexten-_archive_*`, so the archived
`feed_candidates.json` could not be inspected here. Direct feed validation from the dev box confirmed the key signal:

```text
https://astralcodexten.substack.com/feed validated=True item_count=20 root_tag=rss
https://noahpinion.substack.com/feed validated=True item_count=18 root_tag=rss
https://www.notboring.co/feed validated=True item_count=14 root_tag=rss
```

## 픽스

- F: added `engine/recognizers/substack.py` so `*.substack.com/`, `/archive`, and `/feed` use the known RSS config path.
- C: moved `/feed` to the front of well-known feed discovery and capped well-known feed validation at 3s. This keeps lite
  probe from spending the broader discovery timeout on each guessed RSS endpoint while still recording validated feeds.

## 회귀 검증

- `tests/recognizers/test_substack.py` covers direct Substack root/archive/feed recognition and negative hosts.
- `tests/probe_heuristics/test_substack_feed_discovery.py` covers `/feed` discovery with `validated=true` and the 3s
  well-known timeout cap.
- 영향 범위: Substack direct URL recognizer adds a new platform slug for matching Substack URLs; probe change only caps
  `source=well-known-path` feed validation timeout and leaves explicit page/feed links on the caller timeout.

## escalate (allow-list/ownership)

`scripts/register.py:_heterogeneous_hub_check` still needs the L3 guard: if `digest.feed_candidates` or
`digest.list_candidates.rss_feed_urls` contains a fetch-validated RSS/Atom feed, `clean article cluster 0` should not
become a heterogeneous-hub reject by itself. This chunk did not edit `scripts/register.py` because that file is shared
with chunk-1; merge after chunk-1 or apply the L3 guard in the owning branch.

## 일반화 메모

This is not site-specific. The same `/feed` recovery path applies to direct Substack subdomains and custom-domain
Substack/Ghost/Buttondown-like newsletter sites when the RSS endpoint validates as non-empty XML.
