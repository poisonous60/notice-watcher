---
slug: host_aljazeera-com_root_2ac8d25a
url: https://www.aljazeera.com/
status: ✅ preflight b-hit 회복 + config 등록 (baseline 25건, httpx_html RSS)
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, title_nonempty, post_id_unique]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [blogcms-gen2, western-news, rss-fallback, root-homepage]
requested_by: batch
---

## 무엇이 일어났나

`/watch https://www.aljazeera.com/` batch gen_fail. 기존 자동 생성 시도는 `playwright_html` 로 root homepage의 `main article` 계열 selector를 잡았지만, probe digest 기준 첫 글 URL 추출이 없고 정적 반복 후보도 의미 있는 글 row가 없었다. 실패는 `[FAIL] posts_nonempty: 0건`, 이전 attempt에는 liveblog row의 빈 title과 `post_id_unique` 중복도 있었다.

preflight b-hit: 실패 이후 `79ff0de`, `34e74f2` 영향 영역 commit이 있어 `python scripts/register.py --reuse-probe "https://www.aljazeera.com/"` 를 먼저 실행했다. 현재 generator는 feed 후보를 활용해 `https://www.aljazeera.com/rss` 기반 config를 생성했고, 4번째 attempt에서 통과했다.

## 무엇을 바꿨나

`configs/host_aljazeera-com_root_2ac8d25a.json` 생성. `strategy=httpx_html`, list는 RSS `item` row, `guid/link/title/pubDate` 기반으로 `post_id/title/url/published_at` 를 뽑는다. article은 HTML fallback selector로 `ArticleBody`, `article`, `main article` 을 사용한다.

## Track B 검토

track-B 메모: root homepage HTML 자체는 client/render 구조와 liveblog 중복 노출 때문에 일반 HTML selector로 안정화하기 어렵고, 이번 config는 feed fallback으로 닫았다. allow-list 밖인 `probe/`·`generate/` 변경은 하지 않았다. 누적 query상 `posts_nonempty`는 trigger=true지만, 이번 세션 지시는 case 기록만 허용했다.

## 회귀 검증

- `preflight: b-hit — host_aljazeera-com_root_2ac8d25a [79ff0de, 34e74f2]`
- `python scripts/register.py --reuse-probe "https://www.aljazeera.com/"` → PASS, baseline 25건.
- `validate_config` → OK.

