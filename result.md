# 2026-05-28 games-indie-news-01 gen_fail audit

## Cross-site Result

- Track B shipped one generic F-layer fix: XenForo RSS builder now uses `/index.php?forums/-/index.rss` and extracts numeric thread IDs from `<link>`.
- Track A shipped three requested configs: Bay 12 dwarves, Terraria Porta root, Mega Crit news.
- Community PlayStarbound was audited only; no config was added.
- No git add/commit/push, N100 action, cases index, or DB backfill was run.

## Slug Results

| Slug | Live evidence | Track B decision | Action | Smoke |
|---|---|---|---|---|
| `host_bay12games-com_dwarves_230ae845` | 200; 246 `li.dev_progress[id]` inline rows | all-miss; single-site inline devlog | Track A config | rc=0, baseline 30 |
| `host_forums-terraria_root_02d8aba0` | 200; 20 `div.porta-article-item` rows | generic XenForo RSS fixed separately; portal semantics need config | Track A config | rc=0, baseline 20 |
| `host_community-plays_root_dc9ef028` | 200; forum index with 22 `div.nodeText` and 5 recent threads | F partial: XenForo RSS now fetches 6 rows, but target board ambiguous | audit only | no config added |
| `host_megacrit-com_news_4cc63275` | 200; 32 `article.news-card` rows | all-miss; one Hugo positive only | Track A config | rc=0, baseline 30 |

## Changed Files

- `engine/recognizers/xenforo.py`
- `tests/recognizers/test_xenforo.py`
- `configs/host_bay12games-com_dwarves_230ae845.json`
- `configs/host_forums-terraria_root_02d8aba0.json`
- `configs/host_megacrit-com_news_4cc63275.json`
- `docs/cases/_generic_xenforo_index_php_rss_2026-05-28.md`
- `docs/cases/host_bay12games-com_dwarves_230ae845.md`
- `docs/cases/host_forums-terraria_root_02d8aba0.md`
- `docs/cases/host_community-plays_root_dc9ef028.md`
- `docs/cases/host_megacrit-com_news_4cc63275.md`

## Verification Log

- XenForo recognizer RED: expected failures before code change for RSS URL shape, `index.php?` recognition, subpath URL, and post_id source.
- XenForo recognizer GREEN: all 12 checks passed after the engine change.
- Config schema validation: three new configs passed `engine.config_schema.validate_config`.
- Register smokes:
  - Bay12: `register.py --config ...230ae845.json` rc=0, baseline 30, list-only body warning expected.
  - Terraria: `register.py --config ...02d8aba0.json` rc=0, baseline 20.
  - Mega Crit: `register.py --config ...4cc63275.json` rc=0, baseline 30.

