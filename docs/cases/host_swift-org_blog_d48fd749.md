---
slug: host_swift-org_blog_d48fd749
url: https://www.swift.org/blog/
status: ✅ 수동 config (Atom feed + httpx_html XML, 20건 baseline)
outcome: handcrafted
date: 2026-05-22
fix_layer: E
failure_keys: [posts_nonempty, static_vs_headless, inline_json_available, feed_available]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [swift, blog, atom-feed, xml-feed, static-vs-headless, hand-config]
---

## 무엇이 일어났나

자동 생성은 `div.blogs-wrapper > a.post-link` 를 잡았지만 마지막 검증에서 `posts_nonempty: 0건` 으로 실패했다.
probe 는 headless DOM 에서 164개 blog tile 을 봤고, 정적 HTML 안에는 `script#post-data` JSON island 와
`https://www.swift.org/atom.xml` Atom feed 후보가 같이 있었다.

### 진단 (§2 진입 강제 인용)

1. last_feedback `[FAIL]`: `[FAIL] posts_nonempty: 0건`
2. diagnosis verdict: `정적 HTTP로 충분`
3. 실패케이스 매칭: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건` / 목록 추출 실패). 근거: 목록 후보 자체는 있으나 자동 config 의 list 추출이 0건.
4. 분기: 2e 수동 config. Atom feed 가 있어 손어댑터나 Playwright 없이 선언적 config 로 충분.
5. 누적 cross-check: 사용자 지시로 `cases_index.py query` / INDEX / DB backfill 은 실행하지 않음.
6. preflight: `b-hit — host_swift-org_blog_d48fd749 [a9c5da5]`. 현재 코드의 `register.py --reuse-probe` 는 성공했지만 `playwright_html` 로 생성되어, 더 단순한 Atom feed config 로 교체.

## 픽스

`https://www.swift.org/atom.xml` 을 XML 목록으로 사용했다.

- `strategy: httpx_html`
- `list.row_selector: entry`
- `post_id`: `<id>` 의 `/blog/<slug>/`
- `title`: `<title>` + `html_unescape`
- `url`: `<link href=...>`
- `published_at`: `<updated>` ISO timestamp
- `article.content`: 글 페이지의 `section#post .details`

## 검증

- `python scripts/register.py --reuse-probe "https://www.swift.org/blog/"` PASS: 현재 파이프라인은 baseline 30건 config 생성 가능.
- `python scripts/register.py --config configs/host_swift-org_blog_d48fd749.json` PASS: baseline 20건.
- 직접 `make_adapter` 스모크 PASS: 5건 목록, 상위 3건 본문 길이 18507 / 8317 / 15714자.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.

## 트랙 B 검토

- 2a recognizer: 단일 사이트 blog feed라 플랫폼 recognizer 로 일반화할 근거 부족.
- 2b `--article-url`: 첫 글 URL 은 정상 (`/blog/whats-new-in-swift-april-2026/`).
- 2c probe 휴리스틱: feed 후보와 inline JSON 후보가 이미 probe 산출물에 있음. 새 휴리스틱 필요 없음.
- 2d probe 오작동: 아님. 정적 vs headless 차이를 note 로 표시했고 feed 후보도 노출됨.
- 2e 수동 config: 선택. 가장 작은 안정 표면은 Atom feed 기반 config.
