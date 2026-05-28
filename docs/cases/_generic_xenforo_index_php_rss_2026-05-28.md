---
slug: _generic_xenforo_index_php_rss_2026-05-28
url: https://community.playstarbound.com/
status: "✅ F-layer XenForo RSS route/post_id hardening"
outcome: improved
date: 2026-05-28
fix_layer: F
failure_keys: [posts_nonempty, post_id_stable_shape, xenforo_rss]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/xenforo.py]
tags: [xenforo, rss, track-b, games-indie-01]
---

## Summary

Track B hit: XenForo RSS generation was too narrow. Some XenForo installs serve the compatible feed at
`/index.php?forums/-/index.rss`, and XenForo 1.x can put a full URL in `<guid>`, making `guid` a bad
stable post_id. The recognizer now emits the compatible `index.php?` feed URL and extracts the numeric
thread id from `<link>` before falling back to `<guid>`.

## 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema | no-fit | Existing schema can express RSS URL and post_id fallback chain. |
| D retry feedback | no-fit | Retry can hint about post_id, but it cannot discover that the platform feed URL should be `index.php?forums/-/index.rss`. |
| C probe digest | no-fit | Probe already detects `xenforo_platform`; the failure is the config built from that signal. |
| B few-shot | no-fit | This is known-platform dispatch, not LLM few-shot generation. |
| A system rules | no-fit | Prompt guidance does not run for pre-LLM XenForo dispatch. |
| F engine | hit | `engine/recognizers/xenforo.py` owns the generated RSS config. |

## Verification

- RED: `tests/recognizers/test_xenforo.py` failed for `build_config_rss_shape`, `index_php_rss_url_recognized`, `subpath_install_preserved`, `subpath_index_php_rss_recognized`, and `post_id_prefers_link_thread_id`.
- GREEN: the same recognizer run passed all 12 checks.
- Live smoke without registering PlayStarbound: `build_config("https://community.playstarbound.com/")` fetched 6 RSS posts; first IDs were `181780`, `181771`, `181770`.
- Regression scope: root URL recognition remains disabled; only probe-confirmed XenForo or distinctive RSS/whats-new URLs use this builder.

