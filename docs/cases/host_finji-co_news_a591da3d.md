---
slug: host_finji-co_news_a591da3d
url: https://www.finji.co/news/
status: 🧩 수동 config — /news HTML의 product link 후보 대신 검증된 /feed.xml RSS를 폴링
outcome: handcrafted
date: 2026-05-26
failure_keys: [gen_fail, llm_api_unavailable, rss_available, product_link_first_candidate]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [finji, rss, feed-xml, static-html, handcrafted-config]
requested_by: hand-config-codex-20260526
---

## 무엇이 일어났나

대상 URL:

```
https://www.finji.co/news/
```

preflight: miss — 기존 `configs/host_finji-co_news_a591da3d.json` 없음, recognizer 매칭 없음, 로컬 snapshot에는 기존
`output/poll_state`/`output/probe` artifact가 없었다. N100 접속은 이번 작업의 hard stop 범위라 시도하지 않았다.

현재 dev box에서 `python scripts/register.py "https://www.finji.co/news/"`를 재실행했다. probe는 성공했지만 생성 단계에서
Gemini API key 0개로 4회 실패해 `.FAILED.json`이 다시 생성됐다.

```
생성 실패: LLM 호출 실패 (gemini): 모든 Gemini API 키(0개) quota 소진
```

## 진단 근거

로컬 probe 결과:

- `feed_candidates.json`: `https://www.finji.co/feed.xml`이 `validated=true`, `root_tag=rss`, `content_type=application/xml`.
- `list_candidates.json`: 첫 HTML 반복 후보가 `ul > li`, sample URL `https://finji.co/games/868Back/`로 product card였다.
- `list_candidates.json`: 실제 news row 후보도 존재했다. `div.posts.news-grid > div.news-card.large.news`, child_count 6.
- `robots.json`: `/robots.txt` 404, `crawl_delay=null`, `disallow=[]`.
- 직접 feed fetch + XML 파싱: `https://finji.co/feed.xml`의 `channel > item` 364건 확인.

HTML `/news/`에는 product/navigation 후보와 news card 후보가 섞여 있다. feed는 같은 사이트가 명시적으로 노출한 RSS이고
article URL이 `/news/YYYY/MM/DD/*.html`로 안정적이라, HTML selector보다 feed 기반 config가 더 작고 덜 취약하다.

## 해결

`configs/host_finji-co_news_a591da3d.json`을 추가했다.

- strategy: `httpx_html`
- list URL: `https://finji.co/feed.xml`
- row selector: `channel > item`
- `post_id`/`url`: RSS `guid`
- `published_at`: RSS `pubDate`
- article content: `div.post-content`, fallback `article.post`

RSS item에 `<title>`/`<link>`가 비어 있어 list title은 URL path에서 만든 fallback을 사용한다. 새 글 fetch 때는 article page의
`h1.post-title`로 title을 enrich한다.

polite sleep은 probe 권장 5초+와 docs 기본 지침에 맞춰 `min=5`, `max=6`으로 명시했다. `robots.txt`는 404라 별도
`Crawl-Delay`는 없었다.

## 검증

`python scripts/register.py --config "configs/host_finji-co_news_a591da3d.json"`:

```
✅ 등록 완료 — baseline 30건
https://finji.co/news/2026/05/02/Newsletter.html  2026-05-02T09:55:00-04:00  2026 05 02 Newsletter
```

`validate_built_config(fetch_articles=2)`:

```
ok=True n_posts=30
PASS posts_nonempty 30건
PASS post_id_unique
PASS post_id_stable_shape
PASS title_nonempty
PASS published_at_iso 30/30 글에 날짜 있음
PASS article_body_len 6626자, 13053자
```

`python scripts/probe_smoke.py --stage 3 --stage 5`:

```
[stage 3] configs validate + make_adapter
  257 / 257 OK
[stage 5] heuristic units (tests/probe_heuristics/)
  108 파일 · 1235 케이스 · 0 FAIL
summary PASS 1493 FAIL 0 WARN 0 SKIP 0
```

## 일반화 검토

- 2a platform recognizer: X. Finji 단일 사이트의 `/feed.xml` 노출로, 범용 recognizer를 추가할 만큼 반복 패턴이 아니다.
- 2b `--article-url`: X. probe가 실제 news article도 잡을 수 있었지만 root 원인은 article URL 하나가 아니라 HTML 후보 혼재와 LLM 생성 실패다.
- 2c probe/schema/prompt 개선: X. probe가 이미 RSS 후보와 HTML news 후보를 추출했다. 이번 실패는 local LLM API unavailable 및 단일 사이트 선택 문제다.
- 2d probe bug: X. `/games/868Back/` 후보는 HTML에 실제 존재하는 product/navigation 반복 링크다.
- 2e config: O. 검증된 RSS feed를 직접 폴링하는 단일 사이트 config가 최소 변경이다.

일반화 안 되는 이유: `/feed.xml` feed가 RSS인데 item title/link가 비어 있고 guid/description/article page 조합으로 보완해야 한다. 현재는 Finji 사이트 전용 구조다.

## 자가 점검 (§6)

1. **자리**: F. engine 코드는 새로 쓰지 않았지만, 자동 생성 실패를 단일 사이트 수동 config로 해결한 handcrafted fix다.
2. **이전 케이스**: 이번 작업에서는 `cases_index.py query`/DB backfill을 실행하지 않았다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: `register.py --config`, in-memory config validation, `probe_smoke --stage 3 --stage 5`.
5. **outcome=handcrafted**: RSS field mapping과 article selector를 손으로 고른 단일 사이트 config다.
6. **fixture**: 새 strategy/engine/heuristic 변경이 아니므로 fixture 추가 없음.
7. **트랙 B 0건 사유**: 위 일반화 검토 참조.

## hard stop 메모

요청에 따라 `git add`/`git commit`/`git push`, N100 ssh/deploy, `scripts/cases_index.py`, `--backfill-db`,
`docs/cases/INDEX.md` 갱신은 수행하지 않았다.
