---
slug: host_404media-co_root_9e71a06a
url: https://www.404media.co/
status: Mastodon false-positive detector narrowed; 404media/WordPress/Tailscale social-link pages no longer match fresh detection
outcome: improved
date: 2026-05-21
fix_layer: C
failure_keys: [mastodon_platform_false_positive, social_link_mastodon, stale_probe_artifact]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [probe/extract.py]
tags: [mastodon, false-positive, blogcms, probe-heuristic, blog-index]
---

## 무엇이 일어났나

Mastodon platform reject 는 Mastodon 앱 셸을 게시판이 아닌 social instance 로 빠르게 거부하기 위한 신호다.
그런데 `probe/extract.py:detect_mastodon_platform` 의 조건 중 `"<noscript" in low and "mastodon" in low`
가 너무 넓었다. 일반 블로그/CMS 목록 페이지에도 analytics 용 `<noscript>` 와 footer/social 링크의
`Mastodon` 문자열이 같이 있으면 Mastodon instance 로 오인했다.

확인한 false-positive 패턴:

| slug | URL | Mastodon 문자열 출처 |
|---|---|---|
| `host_404media-co_root_9e71a06a` | `https://www.404media.co/` | `social-links__item mastodon` footer link |
| `host_wordpress-org_news_6a775d83` | `https://wordpress.org/news/` | WordPress `.wp-social-link-mastodon` CSS/social link |
| `host_tailscale-com_blog_07031656` | `https://tailscale.com/blog/` | `hachyderm.io/@tailscale` follow link |

셋 모두 `div#mastodon`, `streaming_api`, `/api/v1/streaming`, `generator=Mastodon` 같은 앱 셸 신호는 없었다.

## 무엇을 바꿨나

`detect_mastodon_platform` 에서 넓은 `<noscript>` + `mastodon` 조건을 제거했다.
Mastodon positive 판정은 유지되는 강한 앱 셸 신호만 본다:

- `<div id="mastodon">`
- initial state 의 `streaming_api`
- `/api/v1/streaming` 링크
- `<meta name="generator" content="Mastodon...">`

## 검증

- positive fixture: `techhub.social` 형태의 `div#mastodon` + `streaming_api` HTML 은 계속 Mastodon 으로 감지됨.
- negative fixture: 404media, WordPress News, Tailscale Blog 의 social-link 축약 HTML 은 모두 `None`.
- 실제 local artifact 의 `list.html` 3개를 새 함수로 직접 검사해 모두 `None`.
- `python tests/probe_heuristics/test_detect_mastodon_platform.py` PASS (13 cases).

## register 재시도

codex 가 본 `--reuse-probe` 3건은 기존 `list_candidates.json` 의 stale `mastodon_platform`
값을 재사용해 rc=3 으로 남았다 (HARD-STOP allow-list 가 output/ 재생성 금지). fix 머지 후
Claude 가 **fresh full probe** 로 재등록 (stale digest 자연 폐기):

| slug | 결과 |
|---|---|
| `host_404media-co_root_9e71a06a` | ✅ rc=0 등록 (httpx_html, baseline 12건) |
| `host_wordpress-org_news_6a775d83` | ✅ rc=0 등록 (httpx_html, baseline 10건 — "WordPress 7.0 Armstrong" 등 실제 글) |
| `host_tailscale-com_blog_07031656` | ⚠ rc=1 `[FAIL] probe_timeout` — fresh probe 120s 초과 (heavy Next.js hydration hang). 같은 batch 의 register 300s timeout fix(34e74f2)가 잡아 clean fail. mastodon 오탐 아님 — httpx_html 수동 config 별 작업 (GEN). |

결론: mastodon 오탐 root-cause 봉합 + 2/3 사이트 fresh 재등록. tailscale 은 detect 오탐 아닌
probe hang (별 트랙).
