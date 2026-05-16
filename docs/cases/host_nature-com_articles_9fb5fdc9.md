---
slug: host_nature-com_articles_9fb5fdc9
url: https://www.nature.com/articles/d41586-018-05791-w
status: ❌ 거부 (Nature News 단일 article — 게시판 아님). 인식기 fast-path skip_learn=True + probe heuristic article_meta_signals 신호.
outcome: rejected_with_policy
date: 2026-05-16
fix_layer: F+C
failure_keys: [single_article_page, og_type_article, schema_news_article, diverging_first_article, board_shape_false_positive]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, engine/recognizers/__init__.py, probe/extract.py, probe/_contract.py, scripts/probe.py, scripts/register.py]
tags: [single-article-reject, recognizer-fast-path, skip-learn, probe-heuristic, og-type-article, schema-newsarticle, nature]
requested_by: poi23619 (preview)
---

## 사용자 의도

사용자가 `nature.com/articles/d41586-018-05791-w` URL 을 `/preview` 로 등록 시도. 이 URL 은 Nature 의 *단일 뉴스 article*. Nature 는 매일 수십 article 을 다양한 섹션으로 발행 — `/articles/<doi-like-id>` 는 그 *한 글* 의 canonical URL. 보드 X.

## probe + LLM 처리 흔적 (FAILED.json)

- `last_feedback: [FAIL] posts_nonempty: 0건`
- LLM 추측 보드 URL: `https://www.nature.com/naturecareers/jobs/` (커리어 잡 리스트 — 완전히 다른 섹션). row 0건.
- `[warn] matches_probe_first_article: probe first_article_url='https://www.nature.com/naturecareers/job/12856430/...'`

## 진단 — meta 신호 + 발산 first_article

- `og:type=article` ✅
- JSON-LD `@type: NewsArticle` ✅
- input path-prefix: `/articles`
- probe first_article path-prefix: `/naturecareers` ← **다른 섹션**

두 신호 결합 = 단일 article 페이지. board_shape_check 는 in-article 추천/관련 article 링크의 same-host 신호로 false-positive 통과. nav_only_same_host 는 outside_nav=1 (article body 끝 some breadcrumb) 때문에 안 잡힘.

## 픽스 (fix_layer: F+C)

**F** — `engine/recognizers/article_page_reject.py` 에 nature.com 패턴 추가:
```python
(re.compile(r"^https?://www\.nature\.com/articles/[^/?#]+/?(?:[?#].*)?$", re.I),
 "nature.com 단일 article (`/articles/<doi>`) — 게시판 아님. ...",
 True)  # skip_learn=True
```

`skip_learn=True` 이유: Nature 의 *실제 보드* URL 중 `/articles?type=news` 같은 쿼리-있는 형태가 있음. 학습 시 `_extract_url_pattern` 이 `/articles` 까지만 추출 → 보드까지 차단됨. REJECTED 마커만 박고 learned_blacklist 학습 X.

**C** — `probe/extract.py:article_meta_signals` 신규 휴리스틱:
- `<meta property="og:type" content="article">` 검출
- JSON-LD `<script type="application/ld+json">` 안 `@type` 이 schema.org article-shaped 타입 (NewsArticle/Article/BlogPosting/ScholarlyArticle/...) 인지
- microdata `itemtype` 의 마지막 segment 매칭
- 셋 중 하나라도 매칭이면 `is_article_page=True` + dict 반환, 아니면 None

`scripts/register.py:_meta_article_diverging_check` 게이트:
- `is_article_page=True` AND `first_article_url` 첫 path-segment ≠ input URL 첫 path-segment → REJECT (`_save_rejected(..., learn=False)`)
- omate 류 *우연히* article 마크업 박은 보드 페이지는 first_article 이 같은 path-prefix → 통과 (false-positive 차단).

**왜 두 자리 다?** Nature 는 인식기 fast-path 가 *지금* 잡지만, 미래의 *unknown host* Nature-like 사이트 (블로그 / 학술지 / 뉴스 사이트) 가 추가될 때 인식기에 손-패턴 안 박아도 게이트가 자동으로 잡음. 인식기 = fast-path (probe 비용 0), 게이트 = generalization fallback.

## 검증

새 휴리스틱을 실제 probe artifact 에 적용:
| slug | input path-prefix | first_article path-prefix | meta signals | 게이트 verdict |
|---|---|---|---|---|
| nature (article) | `/articles` | `/naturecareers` | og + NewsArticle | **REJECT** ✅ |
| omate (board, og:type=article) | `/news` | `/news` | og + NewsArticle | 통과 ✅ |

→ false-positive 0.

## 트랙 B 후보 — 검토

- **2a (인식기)**: ✅ Nature 패턴 추가 (즉시 fast-path).
- **2b (--article-url)**: ❌ input 자체가 article URL.
- **2c (probe heuristic)**: ✅ `article_meta_signals` + `_meta_article_diverging_check`. 미래 Nature-like unknown host 자동 커버.
- **2d (probe artifact)**: ❌ artifact 정상.

→ 결론: 2a + 2c 한 PR.

## 사용자 후속

`/watch <보드 URL>` 권유. Nature 보드 후보: `https://www.nature.com/news`, `https://www.nature.com/research-articles`, `https://www.nature.com/subjects/<topic>`. 단 robots.txt 와 폴링 정책 확인 필요.
