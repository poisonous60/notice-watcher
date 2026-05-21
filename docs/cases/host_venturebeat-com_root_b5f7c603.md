---
slug: host_venturebeat-com_root_b5f7c603
url: https://venturebeat.com/
status: ✅ preflight b-hit 회복 + config 등록 (baseline 8건, httpx_html)
outcome: handcrafted
date: 2026-05-21
failure_keys: [post_id_unique]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [blogcms-gen2, western-news, dedup, root-homepage]
requested_by: batch
---

## 무엇이 일어났나

`/watch https://venturebeat.com/` batch gen_fail. 자동 생성은 `main article` / `main article.flex.flex-col.gap-12` 를 row로 잡아 같은 article URL이 여러 card 영역에서 반복되어 `[FAIL] post_id_unique: 중복 3건` 으로 실패했다.

preflight b-hit: 실패 이후 `79ff0de`, `34e74f2` 영향 영역 commit이 있어 `python scripts/register.py --reuse-probe "https://venturebeat.com/"` 를 먼저 실행했다. 현재 generator는 더 좁은 section row selector를 골라 1번째 attempt에서 통과했다.

## 무엇을 바꿨나

`configs/host_venturebeat-com_root_b5f7c603.json` 생성. `strategy=httpx_html`, list row는 `section.container-fluid.mt-50 > div.mt-32 > div > article.flex.flex-col.gap-12` 로 좁혀 중복 카드를 제외한다. `post_id` 는 `^/category/slug` 형태의 두 path segment만 사용하고, article body는 `div.article-body` 를 사용한다.

## Track B 검토

track-B 메모: 중복 원인은 homepage 내 hero/card 재노출이다. 누적 query상 `post_id_unique`는 trigger=true지만, 이번 지시는 `probe/`·`generate/` 변경 금지라 dedup vocabulary/validator 개선은 case 기록만 남긴다.

## 회귀 검증

- `preflight: b-hit — host_venturebeat-com_root_b5f7c603 [79ff0de, 34e74f2]`
- `python scripts/register.py --reuse-probe "https://venturebeat.com/"` → PASS, baseline 8건.
- `validate_config` → OK.

