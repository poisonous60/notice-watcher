---
slug: host_openai-com_index_47fc1c1b
url: https://openai.com/index/attacking-machine-learning-with-adversarial-examples/
status: ❌ 거부 (OpenAI 단일 글페이지 — 게시판 아님; 보드 `/news/` Cloudflare 차단)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, single_article_page, fetch_list_403, cloudflare_blocked, openai_index]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [reject-marker, recognizer-fast-path, cloudflare-blocked, single-article, openai]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview https://openai.com/index/attacking-machine-learning-with-adversarial-examples/` → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] fetch_list: 실행 실패: HTTPStatusError: Client error '403 Forbidden' for url 'https://openai.com/news/'`.

## 진단

사용자 입력이 *글페이지* (`/index/<slug>/`). probe 가 `/index/<slug>/` 직접 GET 은 200 받았으나 list_candidates `first_article_url='https://openai.com/index/openai-technical-goals/'` (related article — sidebar). Gemini 가 보드 `/news/` 를 url_template 으로 추정 → fetch_list 시 Cloudflare 403.

`diagnosis.json` `verdict='정적 HTTP로 충분'` 이지만 실제는 보드 URL Cloudflare 보호 (anti-bot). 게이트 통과 이유:
- `nav_only_same_host=None` (same-host repeating pattern 0 — script/meta 등만)
- `article_meta_signals=None`
- `row_external_host.external_ratio=0.714` (외부 arxiv/x.com/chatgpt 다수 — 글 본문 안 인용 링크)

→ 글페이지가 *single article* 인데 게이트 미커버. Gemini 가 보드 추정도 잘못 + 403 차단.

매칭 `§2g (not_a_board) + §1 (BLOCKED — 보드 Cloudflare)`.

## 픽스 (트랙 A + B — fix_layer=F)

트랙 A: `.REJECTED.json` 마커 + learned_blacklist (host_suffix=`openai.com`, path_prefix=`/index`). 사용자가 보드 `/news/` 로 다시 시도해도 Cloudflare 자동 등록 불가 — handwritten playwright_html + stealth 가 필요한데 비용/이익 평가 시 보류.

트랙 B: `article_page_reject.py:PATTERNS_REJECT` 에 `openai\.com/index/<slug>/` 추가. `skip_learn=False` 안전 — `/index` vs `/news` 다른 첫 segment, 학습 path_prefix=`/index` 가 보드 `/news/` 안 막음.

같은 PR 인프라 case: `docs/cases/infra_article_page_reject_3_2026-05-17.md`.

## 트랙 B 후보 (자가 점검 §6.7)

- **2a (인식기 PATTERNS 확장)**: ✅ openai 패턴 추가.
- **2b (--article-url)**: ❌ — 입력이 글페이지 자체.
- **2c (probe heuristic — 403 차단 사이트 verdict)**: ❌ 보류. diagnosis 가 `verdict='정적 HTTP로 충분'` 으로 잘못 봤지만 — preflight 단계에서 본 글페이지 직접 GET 은 200 이고 보드 URL 시도는 *Gemini 추정 후* 이라 probe 단에서 자연히 감지 어려움. board_url 결정 후 fetch 단계의 403 → register.py 의 새 verdict 분기 후보지만 같은 패턴 1건째 — 보류.
- **2d (probe artifact 수정)**: ❌.

## 미래 — Cloudflare 우회 보드 등록

사용자가 OpenAI blog 폴링 정말 원하면:
- `docs/사이트 어댑터 추가 가이드.md` 의 `playwright_html` + stealth + `storage_state_path` 자리. arca.live 어댑터 참고.
- `https://openai.com/news/` URL 자체는 `_extract_url_pattern` 가 path_prefix=`/news` 추출 — 위 learned_blacklist 의 `/index` 와 별개 → 자동 차단 안 됨. 손-config 작성 후 `register.py --config` 호출하면 등록 가능.
