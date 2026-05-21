---
slug: host_dl-acm-org_action_18500797
url: https://dl.acm.org/action/showPublications
status: no_change (not_board)
outcome: no_change
date: 2026-05-21
failure_keys: [not_a_board, publication_directory]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, acm, board-shape, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

Playwright+stealth는 ACM 페이지에 200으로 도달했지만, 화면은 쿠키 consent와 publications directory 성격의
페이지였다. 확인한 selector 후보(`.issue-item`, `li.search__item`, publication/journal/loi 링크)는 현재
수집 가능한 최신 글 row로 잡히지 않았다.

## 판단

이 URL은 새 공지나 CFP가 올라오는 board라기보다 ACM publication directory다. board-ness 원칙에 따라
config를 만들지 않았다.

## 검증 메모

- httpx: 403 Cloudflare challenge
- Playwright+stealth: 200, publication directory/consent DOM
- outcome: `no_change`
