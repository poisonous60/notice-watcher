---
slug: host_eccv-ecva-net_Conferences_ce3f7dc7
url: https://eccv.ecva.net/Conferences/2026
status: ✅ 해결 (ECCV 2026 announcements 목록 수동 config, 날짜 보강)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [article_body_len, published_at_iso]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [eccv, conference, announcements, handcrafted-config]
requested_by: batch
---

## 진단

- last_feedback: `[FAIL] article_body_len: post_id=Tutorials 0자 (<100 — content selector 의심)`
- diagnosis verdict: `정적 HTTP로 충분`
- 실패 분류: `docs/config 자동생성 실패 케이스.md` §2b. 목록은 맞지만 본문 selector와 날짜 파싱이 흔들렸다.
- 분기: 2e single config. `div.p-4.rounded-4.firstback li` 목록은 유효했고, 수동 config로 날짜를 `strong`에서 추출했다.
- preflight: b-hit — `register.py --reuse-probe`가 rc=0으로 회복했으나 날짜가 `None`이라 config를 보강했다.
- cross-check: `article_body_len` 누적 16건, `track_b_trigger=true`. 이번 케이스는 특정 conf 페이지의 본문 selector 문제라 generic 코드 변경은 보류했다.

## 검증

`python scripts/register.py --config configs/host_eccv-ecva-net_Conferences_ce3f7dc7.json`

결과: PASS, baseline 2건.

- `Tutorials` — `2026-05-15T00:00:00+09:00`
- `CallForPapers` — `2026-01-24T00:00:00+09:00`

회귀 검증: `probe_smoke --stage 3 --stage 5`.
