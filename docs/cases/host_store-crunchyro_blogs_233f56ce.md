---
slug: host_store-crunchyro_blogs_233f56ce
url: https://store.crunchyroll.com/blogs/news
status: rejected (url_dead)
outcome: rejected
date: 2026-05-22
failure_keys: [probe_timeout, url_dead, store_blog_404]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [batch, crunchyroll, store, url-dead, no-config]
requested_by: batch
---

## 무엇이 일어났나

batch 실패 당시 `register.py`는 Playwright probe에서 120초 timeout으로 끝났다.

- last_feedback: `[FAIL] probe_timeout: probe timeout (120s)`
- preflight: b-hit — 실패 이후 `27ed350`, `5665fa8`가 있었고 최신 코드로 재시도했지만 동일하게 probe timeout.
- probe artifact: `s1.H2.html` 안에 `404 - Page Not Found`가 들어 있고 canonical은 `null`.

## 판단

`https://store.crunchyroll.com/blogs/news`는 현재 라이브 HTTP 응답이 `404 Not Found`다.
정적 GET과 저장된 probe HTML 모두 Salesforce Commerce Cloud의 store 404 shell을 반환한다.

remap 후보도 config로 채택하지 않았다.

- `https://store.crunchyroll.com/blogs`도 404.
- `https://store.crunchyroll.com/news`는 `www.crunchyroll.com/news` canonical의 Crunchyroll News shell이며, 이미 `host_crunchyroll-com_news_02fd4569` config가 담당하는 별도 board다.
- `https://store.crunchyroll.com/collections/new`는 상품 목록이지 news/blog board가 아니다.

따라서 원 URL 기준으로는 게시판이 죽었고, `configs/host_store-crunchyro_blogs_233f56ce.json`은 만들지 않았다.

## 트랙 B

누적 조회에서 `probe_timeout`은 track-B trigger였지만, 이번 케이스의 root cause는 timeout 자체가 아니라 죽은 store blog URL이 heavy 404 shell로 probe timeout을 유발한 것이다.
soft-404/url-dead 계층은 이미 rc=4 split과 soft-404 감지 개선이 들어간 상태이고, 이 단일 store 경로를 위해 recognizer나 prompt를 넓히면 정상 store/product URL 오탐 위험이 더 크다.

## 검증 메모

- `curl -I -L https://store.crunchyroll.com/blogs/news` -> HTTP 404.
- `curl -L https://store.crunchyroll.com/blogs/news` -> `404 - Page Not Found`.
- `python scripts/register.py --reuse-probe "https://store.crunchyroll.com/blogs/news"` -> probe timeout 재현.
- robots/polite_sleep: config를 생성하지 않아 적용 대상 없음.
