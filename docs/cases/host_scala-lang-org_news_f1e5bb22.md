---
slug: host_scala-lang-org_news_f1e5bb22
url: https://www.scala-lang.org/news/
status: 🧩 수동 config — Scala official Atom feed 로 baseline 20건 등록
outcome: handcrafted
date: 2026-05-22
failure_keys: [posts_nonempty, matches_probe_first_article, count_ballpark, feed_available, atom_feed_selector]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [scala, atom-feed, rss-selector-mismatch, hand-config]
---

## 무엇이 일어났나

자동 생성은 `https://www.scala-lang.org/rss.xml` 후보를 선택했지만 마지막 검증에서
RSS selector 인 `rss > channel > item` 을 사용했다. 해당 URL 은 실제로
`https://www.scala-lang.org/feed/index.xml` Atom feed 로 리다이렉트되므로 row 는
`feed > entry` 여야 한다. 그 결과 `posts_nonempty: 0건` 으로 실패했다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`
- `[warn] matches_probe_first_article: probe first_article_url='https://www.scala-lang.org/news/?C=N;O=A' 와 일치하는 글 URL 없음`
- `[warn] count_ballpark: 0건 (probe 후보 child_count≈116)`

`diagnosis.json` 은 `정적 HTTP로 충분` 이라고 봤다. probe 의 HTML 후보는 Apache-style
directory listing row 였고, feed 후보가 실제 최신 글 목록이었다.

### 진단 (§2 진입 강제 인용)

1. last_feedback `[FAIL]`: `[FAIL] posts_nonempty: 0건`
2. diagnosis verdict: `정적 HTTP로 충분`
3. 실패케이스 매칭: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건` / 목록 추출 실패). 근거: feed 후보는 있으나 잘못된 row selector 로 목록 추출 0건.
4. 분기: 2e 수동 config. 공식 Atom feed 로 선언적 config 가 가능하고 손어댑터는 필요 없다.
5. 누적 cross-check: `posts_nonempty` 88건, `matches_probe_first_article` 13건, `count_ballpark` 1건. `posts_nonempty`/`matches_probe_first_article` 는 track B trigger 상태지만 이번 요청의 fix surface 는 단일 slug/host 로 제한되어 shared prompt/probe 변경은 하지 않았다.
6. preflight: `b-hit retry-failed — host_scala-lang-org_news_f1e5bb22 [a9c5da5]`. 현재 코드의 `register.py --reuse-probe` 는 rc=3 catalog false reject 로 종료했다.

## 픽스

`configs/host_scala-lang-org_news_f1e5bb22.json` 을 Atom feed 기반 `httpx_html` config 로 작성했다.

- 목록: `https://www.scala-lang.org/feed/index.xml`, `row_selector: feed > entry`
- `post_id`: Atom `<id>` 에서 `https://www.scala-lang.org/` prefix 와 `.html` suffix 제거
- `title/url/published_at/author/summary`: Atom `title/link@href/updated/author/content`
- 본문: 글 페이지의 `main#inner-main section.content div.content-primary div.inner-box`

## 회귀 검증

- preflight stale check
  - existing config: 없음
  - recognizer: `None`
  - 영향 영역 commit: `a9c5da5`
  - 영향 영역 uncommitted 변경: 0건
  - `python scripts/register.py --reuse-probe "https://www.scala-lang.org/news/"`: rc=3 catalog false reject
- schema validation: `OK`
- `make_adapter` smoke: feed 목록 10건, 첫 3개 본문 길이 6096 / 7199 / 8747자
- `python scripts/register.py --config configs/host_scala-lang-org_news_f1e5bb22.json`: baseline 등록
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS

## 트랙 B 검토

- **2a (플랫폼 config) — X.** Scala site 단일 Atom feed 라 플랫폼 recognizer 로 일반화할 근거가 부족하다.
- **2b (`--article-url`) — X.** 실패의 직접 원인은 첫 글 힌트가 아니라 Atom feed 에 RSS selector 를 적용한 것이다.
- **2c/2d (probe/prompt/engine) — 보류.** feed 후보는 이미 probe 산출물에 있고 XML parser 도 Atom 을 처리한다. 단건 fix 범위를 넘는 prompt/engine 변경은 하지 않았다.
- **2e (수동 config) — O.** 공식 Atom feed 로 posts_nonempty 와 본문 추출을 안정적으로 만족한다.

일반화 안 되는 이유: 이 변경은 Scala 공식 feed 의 Atom 구조를 지정하는 단일 config 이며, generic 추론이나
플랫폼 dispatch 를 개선하지 않는다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 와 `matches_probe_first_article` 는 누적 trigger 상태지만, 이번 요청은 단일 host/slug 처리로 제한했다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 10건, register baseline, stage 3/5 smoke PASS.
5. **outcome=handcrafted**: 수동 selector/config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` XML parsing 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
