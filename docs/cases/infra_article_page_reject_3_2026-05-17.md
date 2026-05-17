---
slug: infra_article_page_reject_3_2026-05-17
url: "(인프라 case — 트리거 = 5 건 동시 처리: mdn/github-wiki-see/ktword/openai/tistory)"
status: 🏗 인프라 (article_page_reject 패턴 5 호스트 추가 + 자가 점검 §6.7 보류 결정 1)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, single_article_page, multi_host_hub, mdn_docs, wiki_mirror, encyclopedia, cloudflare_blocked, tistory_root]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py]
tags: [self-improvement, recognizer-fast-path, single-article-gate-v3, skip-learn]
requested_by: 운영자 (dev box session — FAILED 큐 5건 일괄 triage)
---

## 트리거

`triage.py pull` 직후 큐에서 5건이 모두 §2g (`not_a_board`) 패턴이라는 진단 — 모두 단일 article/hub URL 등록 시도:

| slug | last_feedback | 카테고리 |
|---|---|---|
| host_developer-mozil_ko_47b50435 | `[FAIL] posts_nonempty: 0건` | MDN docs reference 단일 페이지 |
| host_github-wiki-see_m_6c370ddf | `[FAIL] post_id_stable_shape` | GitHub wiki 미러 단일 페이지 |
| host_ktword-co-kr_test_d081a15f | `[FAIL] post_id_unique: 중복 1건` | KT용어집 단일 entry |
| host_openai-com_index_47fc1c1b | `[FAIL] fetch_list: 403 Forbidden` | OpenAI blog 글페이지 (보드 Cloudflare 차단) |
| host_tistory-com_root_c59077fa | `[FAIL] post_id_stable_shape` | Tistory 메인 멀티-블로그 hub |

직전 commit `ba84f1f` 의 v2 (`infra_article_page_reject_2_2026-05-16`) 가 7 호스트 (wiki/terms.naver/britannica/USHMM/nature/iln.ieee/jobplanet) + nav-only fallback + meta diverging gate 박음. 새 5건 모두 v2 미커버 — 게이트 통과 사유:
- MDN: `nav_only_same_host=False` (outside_nav=4) + `article_meta_signals=None`
- github-wiki-see: same-host repeating pattern 0건 (모두 external 참고 PDF)
- ktword: outside_nav=3 (page 안 관련용어 nav tree)
- openai: same-host repeating pattern 0건 + 보드 추정 후 403
- tistory: row 들이 *다른 서브도메인* — same-host check 0건

## 픽스 (fix_layer: F — 2 파일)

### F-1. `engine/recognizers/article_page_reject.py` — 5 패턴 추가

| 호스트 | 패턴 | skip_learn | 이유 |
|---|---|---|---|
| developer.mozilla.org | `^/[a-z]{2,5}(?:-[a-z]{2,5})?/docs/` | True | host_path_prefix=lang(`/ko`/`/en-US`) — MDN Blog `/<lang>/blog/` 안 막기 위해 보수적 |
| github-wiki-see.page | `^/m/<user>/<repo>/wiki/` | False | 호스트 전체 wiki 미러 (article-only) |
| www.ktword.co.kr | `^/test/view/` | False | 호스트 전체 용어집 (article-only) |
| openai.com | `^/index/<slug>/$` | False | `/index` vs 보드 `/news` 다른 첫 segment — 학습 안전 |
| (www\.)?tistory.com | `^/(?:\?.*)?(?:#.*)?$` | True | hub root 만 — 모든 path 차단 (보드 없는 hub 라 사실상 안전) |

### F-2. `tests/recognizers/test_article_page_reject.py` — 14 신규 케이스

기존 26 → 40 케이스. 각 새 패턴 positive + 보드/관련 URL false-positive 차단:
- mdn_docs_ko / mdn_docs_en / mdn_blog_passes
- github_wiki_see / github_wiki_see_root_passes
- ktword_view / ktword_other_path_passes
- openai_index_article / openai_news_passes / openai_index_root_passes
- tistory_root_www / tistory_root_naked / tistory_subdomain_passes / tistory_root_with_query

핵심 false-positive 차단:
- MDN Blog `/<lang>/blog/` 통과 (보드)
- OpenAI `/news/` 통과 (보드 — 차단은 별도 이슈)
- Tistory 개별 블로그 `<sub>.tistory.com/<id>` 통과 (별도 host)
- KT용어집 `/test/abbr_view/...` 통과 (테스트는 다른 path)

## 보류 결정 (자가 점검 §6.7) — 휴리스틱 일반화 후보 2개

5건 처리 중 휴리스틱 후보 2개 식별, **둘 다 보류**:

### 후보 1 — `_external_only_check`

신호: `row_external_host.external_ratio >= 0.95 AND total_count >= 1`. github-wiki-see (1.0/1) + tistory (1.0/3) 둘 다 잡힘.

**보류 사유**: 운영 `host_poly-pizza_root_a38820de` 의 probe artifact 검사:

```
ratio=1.0 total=1 sample=['https://wawasensei.dev/courses/...']
```

poly-pizza 는 board (3D 모델 다운로드 사이트) 인데 row sample 이 *sponsor link* (외부) — false-positive 차단 위험. 임계값 `total>=3` 으로 올리면 github-wiki-see (total=1) 못 잡지만 그건 PATTERNS_REJECT 가 잡음. 일반 휴리스틱은 *명백한 hub multi-host* 만 잡는 게 안전.

**재검토 트리거**: 같은 패턴 미커버 호스트 1건 더 들어오면 — `external_ratio>=0.95 AND total>=3 AND unique_external_hosts>=3` (multi-host hub 만) 게이트 신설.

### 후보 2 — `_multi_host_hub_check`

신호: `external_ratio>=0.95 AND len(set(urlsplit(u).netloc for u in samples))>=3`. tistory 만 잡힘 (3 unique subdomains).

**보류 사유**: 단일 사례 (tistory 메인) — 일반화 over-engineering. 같은 패턴 2건째 (`brunch.co.kr/`, `steemit.com/trending`, `medium.com/` 같은 플랫폼 hub root) 들어오면 휴리스틱화.

## 회귀 검증

- `python tests/recognizers/test_article_page_reject.py` → **40/40 PASS** (기존 26 + 신규 14).
- `python scripts/probe_smoke.py --stage 3 --stage 5` → (실행 결과 commit 직전 박음)
- 운영 36 configs 영향 검사 (probe artifact 의 `row_external_host.external_ratio>=0.5`):
  - `host_poly-pizza_root_a38820de` (ratio=1.0/total=1) — PATTERNS_REJECT 5건 어느 것도 매칭 X (poly-pizza 다른 호스트)
  - `host_quibli-dustyroo_root_216cc634` (ratio=0.5/total=2) — 영향 X
  - 그 외 ratio<0.5 — 영향 X

→ 회귀 0.

## 트랙 B enumerate

이 인프라 commit 자체가 트랙 B (probe 일반화). 각 사이트별 case 는 트랙 A (즉시 거부 마커 + learned_blacklist).

- **2a (인식기 PATTERNS)**: ✅ 5 호스트.
- **2b (--article-url)**: ❌ — 입력이 모두 single article/hub.
- **2c (probe heuristic)**: ❌ 보류 — 위 후보 1+2 결정.
- **2d (probe artifact 수정)**: ❌ — artifact 정상.

## 자가 점검 (§6)

1. **자리**: F (engine/recognizers PATTERNS_REJECT 확장). 휴리스틱(C)/few-shot(B)/schema(E)/retry(D)/엔진코드(F-신규) 어느 것보다 가장 좁은 자리 — 알려진 호스트 명시 차단.
2. **이전 케이스**: `infra_single_article_gate_2026-05-16.md` (v1), `infra_article_page_reject_2_2026-05-16.md` (v2). 같은 자리 (F) — 누적 호스트 4→7→12.
3. **누구 깰까**: 운영 36 configs 중 PATTERNS_REJECT 5건 어느 것에도 매칭되는 운영 사이트 0건 (`recognize_reject` 미커버 확인). 회귀 0.
4. **검증**: test_article_page_reject 40/40 PASS. probe_smoke commit 직전.
5. **outcome=improved, fix_layer=F**.
6. **fixture (§7,§8 의무)**: PATTERNS_REJECT 자체는 `tests/recognizers/test_article_page_reject.py` 가 단일 진실원 — 5 신규 패턴 모두 + false-positive 테스트 추가됨. probe_smoke stage 5 가 이 파일 fixture 자동 발견.
7. **트랙 B 매칭 0개 아님 — 위 enumerate**.
