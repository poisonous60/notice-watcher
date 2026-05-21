---
slug: host_politico-com_root_0e7b5678
url: https://www.politico.com/
status: 🔧 손 config 등록 (baseline 25건, playwright_html; article body may be empty behind Cloudflare)
outcome: handcrafted
date: 2026-05-21
failure_keys: [article_body_len, fetch_list]
fix_layer: F
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [blogcms-gen2, western-news, cloudflare, body-empty-acceptable]
requested_by: batch
---

## 무엇이 일어났나

`/watch https://www.politico.com/` batch gen_fail. 자동 생성은 root list row 자체는 잡았지만 첫 글 article fetch에서 `[FAIL] article_body_len: post_id=00929932 0자` 로 실패했다. preflight b-hit 재시도 후에는 `httpx_html` root 접근이 Cloudflare 403으로 막혀 `[FAIL] fetch_list` 로 실패했다.

probe artifact의 `article.html` 에서는 `div.post-card__body` / `div.rte.rte--card` 가 본문으로 확인됐다. 다만 현재 직접 article URL을 Playwright로 열면 Cloudflare challenge에서 멈춰 본문 DOM이 나오지 않는 상태가 재현됐다.

## 무엇을 바꿨나

`configs/host_politico-com_root_0e7b5678.json` 수동 작성. root list는 `playwright_html` 로 열고 `div.container__slot > div.module.single-column-list.has-bottom-divider` row에서 `live-updates`/`news` article URL, title, 8자리 post id를 추출한다. article selector는 probe에서 확인한 `div.post-card__body`, `div.rte.rte--card`, `article` 순서로 둔다.

현재 poll-time direct article fetch가 Cloudflare에 걸릴 수 있어 `article.body_empty_acceptable: true` 를 명시했다. 봇에는 baseline body-empty 경고가 남고, 목록 기반 새 글 감지는 동작한다.

## Track B 검토

track-B 메모: 이 케이스의 일반화 지점은 "Cloudflare root/list는 Playwright로 통과하지만 direct article fetch는 challenge에 멈춤"이다. `playwright_html` article fetch의 challenge 대기/쿠키 재사용 개선 후보지만 allow-list 밖 코드 변경이라 보류했다.

## 회귀 검증

- `preflight: b-hit — host_politico-com_root_0e7b5678 [79ff0de, 34e74f2]`
- `validate_config` → OK.
- adapter smoke → list 10건, direct article body 0자 재현.
- `python scripts/register.py --config "configs/host_politico-com_root_0e7b5678.json"` → PASS, baseline 25건.

