---
slug: infra_article_page_reject_2_2026-05-16
url: (인프라 case — 특정 사이트 X. 트리거 = host_iln-ieee-org/host_nature-com/host_jobplanet 3 건 동시 처리)
status: 🏗 인프라 (단일 article page 거부 게이트 v2 — recognizer skip_learn + article_meta_signals heuristic + diverging-path gate)
outcome: improved
date: 2026-05-16
fix_layer: F+C
failure_keys: [single_article_page, og_type_article, schema_news_article, diverging_first_article, learned_blacklist_overbroad]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, engine/recognizers/__init__.py, probe/extract.py, probe/_contract.py, scripts/probe.py, scripts/register.py, tests/probe_heuristics/test_article_meta_signals.py, tests/recognizers/test_article_page_reject.py]
tags: [self-improvement, recognizer-fast-path, skip-learn, probe-heuristic, og-type-article, schema-newsarticle, diverging-path-gate, article-page-reject-v2]
requested_by: 운영자 (dev box session)
---

## 트리거

`triage.py pull` 직후 큐에 3 건 (모두 단일 article URL 입력):
- `host_iln-ieee-org_Public_ff9aa2d5` — `/Public/ContentDetails.aspx?id=<GUID>` (콘텐츠 상세)
- `host_nature-com_articles_9fb5fdc9` — `/articles/<doi>` (Nature News article)
- `host_jobplanet-co-kr_contents_ecde1648` — `/contents/news-<N>` (단일 뉴스 기사)

직전 commit `ba84f1f` 의 v1 게이트 (`recognize_reject` PATTERNS + `_single_article_nav_only_check`) 는 4 호스트 (wiki/terms/britannica/USHMM) + nav-only fallback. 새 3 건 모두 v1 미커버 — `outside_nav>=1` 라 nav-only 게이트 통과, 호스트 인식기 X.

## 픽스 (fix_layer: F+C — 8 파일)

### F-1. `engine/recognizers/article_page_reject.py` — 3 패턴 추가 + tuple 형식 확장

PATTERNS_REJECT 항목을 2-tuple `(pattern, reason)` 또는 3-tuple `(pattern, reason, skip_learn)` 둘 다 지원. 같은 첫 path-segment 를 *보드/article 이 공유* 하는 사이트는 `skip_learn=True` 박음 — `_learn_pattern` 의 path_prefix(=첫 segment) 차단이 보드 URL 까지 막는 것 회피.

3 새 패턴:
| 호스트 | 패턴 | skip_learn | 이유 |
|---|---|---|---|
| iln.ieee.org | `^/Public/ContentDetails\.aspx\?` | True | 보드 `/Public/trainingcatalog.aspx` 등이 같은 `/Public` |
| www.nature.com | `^/articles/<id>` (쿼리 없는 단일 path-segment) | True | 보드 `/articles?type=news` 등이 같은 `/articles` |
| www.jobplanet.co.kr | `^/contents/news-\d+` | True | 보드 `/contents/news` 가 같은 `/contents` |

기존 4 패턴 (wikipedia/terms.naver/britannica/USHMM) 는 2-tuple 유지 → `skip_learn=False` (호스트 전체가 article-only 라 path_prefix 차단 OK).

### F-2. `engine/recognizers/__init__.py` — _load_rejects + recognize_reject 시그니처 확장

- `_load_rejects()` 가 2-tuple/3-tuple 둘 다 받아 (name, pat, reason, skip_learn) 4-tuple 리스트 반환.
- `recognize_reject(url)` 반환 `Optional[tuple[str, str, bool]]` (skip_learn 추가).

### F-3. `scripts/register.py:_save_rejected` — `learn` keyword-only 파라미터

기본 `learn=True` (기존 호출 사이트 변경 없음). `learn=False` 시 `_learn_pattern` 호출 *생략* — REJECTED 마커만 박음. `.REJECTED.json` payload 에 `"learned": True|False` 기록 (운영 디버깅용).

### F-4. `scripts/register.py` — recognize_reject 호출 자리에서 skip_learn 전달

```python
rej = recognize_reject(url)
if rej is not None:
    name, reason, skip_learn = rej
    ...
    _save_rejected(slug, url, reason, note=..., learn=not skip_learn)
```

### C-1. `probe/extract.py:article_meta_signals` 신규 휴리스틱

페이지가 *단일 article* 임을 선언한 명시 meta 신호 추출:
1. `<meta property="og:type" content="article">` 매칭.
2. JSON-LD `<script type="application/ld+json">` 안 `@type` 이 schema.org article-shaped 타입 (frozenset 25개: NewsArticle/Article/BlogPosting/ScholarlyArticle/TechArticle/Report/SocialMediaPosting/DiscussionForumPosting/Review/...) 매칭. `@graph` 안 nested 도 재귀 추출.
3. microdata `itemtype` 의 마지막 segment 매칭 (`schema.org/Article` → `article`).

셋 중 하나라도 있으면 dict 반환 (`{has_og_article, schema_article_types, has_microdata_article, is_article_page, signals}`), 아니면 None.

### C-2. `probe/_contract.py` + `probe/extract.py:write_list_candidates` + `scripts/probe.py`

`list_candidates.json` payload 에 `article_meta_signals` 새 키 추가 (`dict|null`, required=False). probe.py phase 7 에서 휴리스틱 호출 → write_list_candidates 가 박음.

### F-5. `scripts/register.py:_meta_article_diverging_check` — 새 게이트

`_single_article_nav_only_check` 직후, `_board_shape_check` *전* 호출. 조건:
- `digest.list_candidates.article_meta_signals.is_article_page == True`
- AND `first_article_url` 존재
- AND `first_article_url` 의 첫 path-segment ≠ input URL 첫 path-segment

→ REJECT (rc=3), `_save_rejected(..., learn=False)`.

`learn=False` 이유: 이 게이트가 잡는 사이트는 보드/article 이 같은 첫 segment 공유할 수 있어 path_prefix 차단이 보드까지 막을 위험.

**false-positive 차단**: 보드 페이지가 *우연히* og:type=article 박은 경우 (omate 류) → first_article_url 이 input 과 *같은* path-prefix → 게이트 통과.

## 검증 (실제 probe artifact)

| slug | meta signals | input seg | first_article seg | gate verdict | 실제 |
|---|---|---|---|---|---|
| host_nature-com_articles_9fb5fdc9 | og + NewsArticle | `/articles` | `/naturecareers` | **REJECT** | article ✅ |
| host_omate-kr_news_3ff5e0f9 (BOARD, og+NewsArticle 박힘) | og + NewsArticle | `/news` | `/news` | 통과 | board ✅ |
| host_iln-ieee-org_Public_ff9aa2d5 | None (meta 없음) | `/Public` | `/public` | 통과 (인식기 fast-path 가 잡음) | article ✅ |
| host_jobplanet-co-kr_contents_ecde1648 | None (SPA — server HTML 에 meta 없음) | `/contents` | `/companies` | 통과 (인식기 fast-path) | article ✅ |

→ **false-positive 0**. 게이트 자체는 nature 1 건 (+ 미래 unknown host) 커버. 나머지 2 건은 인식기 fast-path. 두 자리 보완 관계.

## 테스트

- `tests/probe_heuristics/test_article_meta_signals.py` 신규 (9 case): og only / NewsArticle / @graph nested / microdata / og+schema 둘 / neutral board (None) / ItemList (None) / 깨진 JSON-LD (None) / empty (None).
- `tests/recognizers/test_article_page_reject.py` 확장 (+8 case): 3 새 패턴 positive + 보드 통과 negative + skip_learn 플래그 검증.

## 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` → **294 PASS / 0 FAIL** (35 configs + 30 휴리스틱 파일 / 258 case + coverage 28/28).
- `python scripts/probe_smoke.py` (full) → 300 PASS / 0 FAIL / 4 WARN (diagnosis.json fixture 가 옛것 — 재-probe 권유 WARN, FAIL 아님).
- 새 게이트가 omate (운영 board) 차단 X — `_meta_article_diverging_check` 가 first_article path-prefix 매칭으로 통과시킴.

## 트랙 B 후보 — 자가 검토

이 인프라 commit 자체는 트랙 B (probe 일반화). 각 사이트별 case 가 트랙 A (즉시 거부 마커).

- **2a (인식기 PATTERNS 확장)**: ✅ 3 호스트 추가.
- **2b (--article-url)**: ❌ — 입력이 single article URL 자체라 교정 대상 없음.
- **2c (probe heuristic)**: ✅ `article_meta_signals` 휴리스틱 신규. 미래 *unknown host* Nature-like 사이트 자동 커버.
- **2d (probe artifact 수정)**: ❌ — artifact 정상.

## 자가 점검 (§6)

1. **자리**: F (engine/recognizers 패턴 + register.py 게이트) + C (probe/extract 휴리스틱). 두 자리 보완 — fast-path + structure fallback.
2. **이전 케이스**: `infra_single_article_gate_2026-05-16.md` (직전 v1). 같은 자리 (F+C) — v1 으로 못 잡은 나머지 호스트 패턴 + meta-signal fallback.
3. **누구 깰까**: 기존 운영 35 configs 중 og:type=article 가진 3 건 (omate/gamemeca/quibli). `_meta_article_diverging_check` 의 path-prefix 매칭이 통과시킴 확인 — omate input/first_article 모두 `/news`. 회귀 0.
4. **검증**: probe_smoke `--stage 3 --stage 5` PASS 294/0. 새 fixture 9+8=17 case 0 fail. 실제 omate probe artifact 에 게이트 적용 → 통과.
5. **outcome=improved, fix_layer=F+C**.
6. **fixture (§7,§8 의무)**: 새 휴리스틱 `article_meta_signals` (@heuristic 데코) + `tests/probe_heuristics/test_article_meta_signals.py` 짝 — §8 만족. 새 strategy 추가 X (§7 skip).
7. **트랙 B**: 위 §트랙 B 4 항목 enumerate.
