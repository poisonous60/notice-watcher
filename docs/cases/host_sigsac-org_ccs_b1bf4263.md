---
slug: host_sigsac-org_ccs_b1bf4263
url: https://www.sigsac.org/ccs/CCS2026/
status: ✅ 해결 (CCS 2026 Latest News list-only config, 외부 HotCRP/Google 링크 본문 skip)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [article_body_len, post_id_stable_shape, posts_nonempty, external_host_article]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [sigsac, ccs, conference, latest-news, body-empty-acceptable]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] article_body_len: post_id=https://ccs2026b.hotcrp.com 0자 (<100 — content selector 의심) / post.url host='ccs2026b.hotcrp.com' 가 list host='www.sigsac.org' 와 다름`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2b / §2d. 목록은 `div.news > ul > li`에 있지만 외부 링크 본문과 post_id 정규화가 실패했다.
- 분기: 2e single config. Latest News는 list 자체로 충분하므로 본문은 `body_empty_acceptable`로 비우고, post_id는 URL을 stable slug로 정규화했다.
- preflight: b-hit — `register.py --reuse-probe`는 rc=1.
- cross-check: `article_body_len` 누적 16건, `post_id_unique` 누적 9건, `posts_nonempty` 누적 67건, 모두 `track_b_trigger=true`. 이번 케이스는 외부 HotCRP/Google 링크가 섞인 conf news list라 단일 config로 한정했다.

## 검증

`python scripts/register.py --config configs/host_sigsac-org_ccs_b1bf4263.json`

결과: PASS, baseline 7건. 본문은 의도적으로 비워 알림은 제목/URL/요약 중심이다.

- `ccs2026b-hotcrp-com` — `2026-03-30T00:00:00+00:00`
- `www-sigsac-org-ccs-ccs2026-call-for-call-for-workshops-html` — `2026-02-26T00:00:00+00:00`
- `hotcrp-com-news-2026-security-notice-202601` — `2026-01-27T00:00:00+00:00`

회귀 검증: `probe_smoke --stage 3 --stage 5`.
