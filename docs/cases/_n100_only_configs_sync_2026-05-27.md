---
slug: _n100_only_configs_sync_2026-05-27
url: (N100 → dev box sync)
status: "📦 handcrafted — N100 register 자동생성 config 4건 dev box 회수"
outcome: handcrafted
fix_layer: none
failure_keys: [n100_only_config_drift]
date: 2026-05-27
trigger_slugs:
  - host_docs-cohere-com_changelog_4d5f0e27
  - host_export-arxiv-or_rss_7eae3d19
  - host_indycar-com_News_e4c69ade
  - host_news-opensuse-o_root_7ad67393
tags: [n100-sync, drift]
---

## 컨텍스트

2026-05-27 FAILED 큐 19건 batch-retry 중 `(already registered)` 12건 발견. 이 중 4 건이 *N100 만* 에 config 박혀 있고 dev box `configs/` 에 누락 — N100 자동생성 (`/watch` 또는 batch agentic) 후 dev box pull 안 됨. CLAUDE.md §5 룰 C 의 "사용자 등록 sync" sibling.

배경: N100 register.py 가 auto-discover / agentic 으로 만든 config 는 git 추적이지만 N100 working tree 에 untracked. 다음 dev box pull 은 N100 의 *commit 된 변경*만 받음 → 자동생성 config 영원히 N100-only.

## 회수

```sh
scp aaaa@n100-noticewatcher:notice-watcher/configs/<f> ./configs/<f>
```

4 file 각각 `engine.config_schema.validate_config` PASS + `python scripts/probe_smoke.py` exit 0.

## 회수된 config 4건

| slug | strategy | URL |
|---|---|---|
| `host_docs-cohere-com_changelog_4d5f0e27` | httpx_html | https://docs.cohere.com/changelog |
| `host_export-arxiv-or_rss_7eae3d19` | httpx_html | https://export.arxiv.org/rss/cs |
| `host_indycar-com_News_e4c69ade` | httpx_html | https://www.indycar.com/News |
| `host_news-opensuse-o_root_7ad67393` | playwright_html | https://news.opensuse.org/ |

## E/D/C/B/A/F audit

- E: miss — 스키마 PASS, 변경 X
- D: miss — retry feedback 변경 X
- C: miss — probe 휴리스틱 변경 X
- B: miss — few-shot example 변경 X
- A: miss — system 룰 변경 X
- F: miss — engine 코드 변경 X (단순 config sync)

## 일반화 후보 (deferred → infra 개선)

N100 → dev box config drift 자동 sync infrastructure 부재. 매 batch 후 손-scp 로 처리. 후속 후보:
1. `scripts/triage.py pull` 에 `configs/` diff 도 같이 pull (option flag)
2. `scripts/remote.py sync-configs` 신규 command — N100 에 dev box 미보유 config 검출 후 fetch
3. N100 register.py 가 자동생성 config 만들 때 dev box 알림 (DM/notification)

본 case 의 작업 범위 밖 — deferred.

## 검증

- `python scripts/probe_smoke.py` exit 0 (1666 PASS, 0 FAIL)
- 4 config 모두 `validate_config` PASS
- N100 에는 이미 동일 file 존재 (sync target = dev box only)

## outcome 분류

`handcrafted` — single config 단위 coverage 회수, generic 추론 개선 0, 일반화 mechanism 0. `improved` 아님 (generic ≠ sync infra 부재 봉합).
