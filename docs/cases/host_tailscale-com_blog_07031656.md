---
slug: host_tailscale-com_blog_07031656
url: https://tailscale.com/blog/
status: ✅ 등록 완료 (static HTML httpx_html config; Playwright timeout 우회)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [probe_timeout]
config_strategy: httpx_html
tags: [tailscale, nextjs, static-html, batch-2026-05-21-blogcms-gen3]
---

## 원인

probe는 Playwright 단계에서 120초 timeout으로 실패했지만, 저장된 `output/probe/host_tailscale-com_blog_07031656/list.html`에는 Next.js SSR 결과가 들어 있었다. `diagnosis.json`도 `정적 HTTP로 충분`으로 판정했고, `main a[href^="/blog/"]`에 실제 블로그 카드가 있었다.

## 처리

- `configs/host_tailscale-com_blog_07031656.json` 추가.
- `strategy=httpx_html`, `row_selector=main a[href^='/blog/']`, `row_required_selector=h3`.
- `post_id`는 `/blog/<slug>` path segment에서 추출하고, 본문은 article page의 `main`을 사용한다.

## 회귀 검증

- `python scripts/register.py --config configs/host_tailscale-com_blog_07031656.json` → PASS, baseline 5건.
- 영향 0개: 새 recognizer/engine 변경 없이 단일 config만 추가했다.

## 트랙 B

일반화 보류. 같은 Next.js timeout이라도 사이트별 SSR markup과 card selector가 다르다. 이번 작업은 Tailscale 단일 config로 충분하고, probe timeout 자체의 엔진 수정은 allow-list 밖이다.
