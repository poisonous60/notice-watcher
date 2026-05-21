---
slug: host_icse2026-github_root_cd78a66a
url: https://icse2026.github.io/
status: no_change (url_dead)
outcome: no_change
date: 2026-05-21
failure_keys: [url_dead, github_pages_404]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, github-pages, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

정적 httpx와 Playwright 모두 GitHub Pages `Site not found` 404 페이지를 받았다.

## 판단

사용자 메모처럼 GitHub Pages transient 가능성은 있지만, 현재 라이브 URL은 board가 아니며 HTTP 404다.
config를 만들지 않았다.

## 검증 메모

- httpx: 404 `Site not found - GitHub Pages`
- Playwright+stealth: 404 동일
- outcome: `no_change`
