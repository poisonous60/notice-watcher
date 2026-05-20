---
slug: host_smashingmagazin_feed_cb3fed96
url: https://www.smashingmagazine.com/feed/
status: ✅ register feed-override (Cloudflare HTML 차단 + 공개 RSS 피드 → 피드로 등록)
outcome: improved
date: 2026-05-20
fix_layer: F
failure_keys: [blocked_bot, cloudflare_html_open_feed]
config_strategy: httpx_html
engine_files_touched: [scripts/register.py, probe/discover.py]
tags: [register, policy, cloudflare, rss, feed-override, batch-2026-05-20-b]
requested_by: catalog 2026-05-20-b
---

## 무엇이 일어났나

batch 2026-05-20-b 의 `smashingmagazine.com/feed/` 가 rc=2 (BLOCKED) 거부. 다른 RSS 는
feed content-sniff fix 후 등록됐는데 이건 계속 막힘.

## 진단

probe 의 HTML 진입 매트릭스 (S1.H2/H3/H4) = `200 BLOCKED_BOT — "Attention Required"`
(Cloudflare 챌린지). `_policy_check` 의 `not _entry_matrix_has_ok_list` → verdict='분류 보류'
BLOCKED 거부 (rc=2). 단 RSS 피드 자체는 **공개** — httpx 200 application/xml 1.1MB,
feed_candidates 에 well-known-path `/rss` status=200 박혀 있음.

즉 Cloudflare 가 **HTML 페이지만 챌린지하고 RSS endpoint 는 열어둠** (흔한 패턴). 우리는 HTML 이
아니라 RSS 만 폴링하면 되므로 BLOCKED 여도 등록 가능해야 함.

## 트랙 B (영구)

`scripts/register.py:_has_verified_feed(digest)` — feed_candidates 에 fetch-검증된 피드
(well-known-path 200 xml 또는 `input-url-feed-fetch` source) 가 있나. `_policy_check` 의
BLOCKED 거부 직전에 체크 → 있으면 등록 진행 (note: 차단 우회 X, 공개 피드 수집).

안전망: 검증 조건이 게이트. cert_or_dns_broken/target_not_found 는 피드 fetch 도 실패 →
검증 통과 못 함 → 자연 제외. path 모양만 추측한 `input-url-feed-path` 도 미검증 제외.

연관: probe/discover 의 feed content-sniff (`_url_serves_feed` raw fetch — headless XML-viewer
DOM 우회) 로 feed_candidates 가 채워진 게 전제. [[host_hnrss-org_newest_1848d6c8]] 참조.

## 회귀 검증

재등록 rc=0 — "HTML 목록 진입은 막힘이나 fetch-검증된 공개 RSS/Atom 피드 존재 — 피드로 등록 진행"
→ 등록 완료. test_body_is_feed 의 _has_verified_feed 5 cases (검증/미검증 경계). probe_smoke
stage3 50/50 stage5 502 cases 0 FAIL.
