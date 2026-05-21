---
slug: host_historians-org_annual-meeting_aae80fef
url: https://www.historians.org/annual-meeting
status: ✅ 해결 (Annual Meeting 관련 article 링크 4건 list-only config)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [fetch_list_403, article_body_len, cloudflare_protected]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [historians, annual-meeting, playwright, body-empty-acceptable]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] fetch_list: 실행 실패: HTTPStatusError: Client error '403 Forbidden' for url 'https://www.historians.org/events/annual-meeting/?page=1'`
- diagnosis verdict: `CLOUDFLARE_PROTECTED_SITE / 정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2a / §2b. httpx URL 후보는 403이고, playwright 목록은 잡히지만 article body 검증에서 실패했다.
- 분기: 2e single config. 목록 링크 자체는 공개 렌더에서 보이므로 `playwright_html` + `body_empty_acceptable`로 list-only 등록했다.
- preflight: b-hit — `register.py --reuse-probe`는 article body 0자로 rc=1.
- cross-check: `fetch_list` 누적 3건, `article_body_len` 누적 16건, 둘 다 `track_b_trigger=true`. 이 사이트는 Cloudflare+본문 selector 문제라 이번 PR에서는 단일 config로 한정했다.

## 검증

`python scripts/register.py --config configs/host_historians-org_annual-meeting_aae80fef.json`

결과: PASS, baseline 4건. 본문은 의도적으로 비워 알림은 제목/URL 중심이다.

- `aha26`
- `awards-prizes-and-honors-conferred-at-the-139th-annual-meeting`
- `how-to-write-alone-together`

회귀 검증: `probe_smoke --stage 3 --stage 5`.
