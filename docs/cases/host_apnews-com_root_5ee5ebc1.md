---
slug: host_apnews-com_root_5ee5ebc1
url: https://apnews.com/
status: 🔧 손 config 등록 (baseline 30건, httpx_html)
outcome: handcrafted
date: 2026-05-21
failure_keys: [title_nonempty, posts_nonempty, article_body_len]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [blogcms-gen2, western-news, empty-link-text, root-homepage]
requested_by: batch
---

## 무엇이 일어났나

`/watch https://apnews.com/` batch gen_fail. 최초 실패는 `[FAIL] title_nonempty` 로, `div.PageList-items > div.PageList-items-item` 안의 첫 `a[href*='/article/']` 가 이미지/overlay 링크라 text가 빈 값이었다. preflight b-hit 후 `--reuse-probe` 재시도에서도 selector가 빈 row나 trending link에 붙어 `posts_nonempty` 또는 `article_body_len` 으로 실패했다.

## 무엇을 바꿨나

`configs/host_apnews-com_root_5ee5ebc1.json` 수동 작성. root HTML의 `div.PagePromo:has(a[href*='/article/'])` 를 row로 잡고, `pick:first_matching + match:"\\S"` 로 빈 anchor를 건너뛰어 첫 non-empty article link text를 title로 사용한다. `post_id/url` 은 같은 row의 AP article URL에서 추출한다. article body는 probe `article.html` 에서 확인한 `div.RichTextStoryBody` 를 1순위 selector로 지정했다.

## Track B 검토

track-B 메모: AP root는 같은 row 안에 빈 overlay anchor와 텍스트 anchor가 같이 있어 field source의 `pick:first_matching`이 핵심이다. generic retry feedback 후보는 있지만 이번 allow-list가 `configs/`와 case 문서만 허용하므로 `probe/`·`generate/` 변경은 보류했다.

## 회귀 검증

- `preflight: b-hit — host_apnews-com_root_5ee5ebc1 [79ff0de, 34e74f2]`
- `validate_config` → OK.
- adapter smoke → list 10건 샘플, 첫 글 body 42913자.
- `python scripts/register.py --config "configs/host_apnews-com_root_5ee5ebc1.json"` → PASS, baseline 30건.

