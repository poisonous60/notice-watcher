---
slug: host_acm-org_code-of-ethics_a1ad42c5
url: https://www.acm.org/code-of-ethics
status: ⚠️ 자동 등록 통과 (baseline 1건 — single article 의심, learned_blacklist false negative 가능성).
outcome: registered-suspicious
date: 2026-05-19
fix_layer:
failure_keys: [single_article_page, baseline_1_only, count_ballpark_warn, learned_blacklist_false_negative]
config_strategy: playwright_html
adapters_changed:
engine_files_touched:
tags: [arxiv-2601-bench, ethics-page, single-article, gate-bypass]
requested_by: 운영자 (arxiv-2601-bench 7건 batch 중 신규 사이트 — bench list 없음, 운영자가 별 추가)
vocab_candidates:
  - candidate: single_article_gate_strengthen
    confidence: low
    evidence:
      - "register.py 출력 (2026-05-19 preflight): baseline 1건, 경고 `count_ballpark(1건 (probe 후보 child_count≈24))`"
      - "URL = `https://www.acm.org/code-of-ethics` = ACM Code of Ethics 페이지 (단일 윤리 강령) — board 아님"
    reasoning: "본 사이트는 *list 페이지 아닌* single article 인데 자동 등록 통과. probe 가 `code-of-ethics` URL 자체를 first_article 로 잡고 (probe first_article_url=`https://www.acm.org/publications/about-publications`), playwright_html strategy 로 baseline 1건 추출. [[infra_single_article_gate_2026-05-16]] + [[infra_article_page_reject_2_2026-05-16]] + [[infra_article_page_reject_3_2026-05-17]] 의 게이트가 본 URL 패턴 못 잡음 — `count_ballpark` 경고만 박힘 (1건 vs probe 후보 24). 게이트 강화 후보. confidence=low — 단일 evidence, ACM domain 자체가 비주류."
    analysis_date: 2026-05-19
    deferred: true
---

## 무엇이 일어났나

`/watch https://www.acm.org/code-of-ethics` → snapshot 의 FAILED.json 에 진입:
- 이전 fail (snapshot mtime 09:41 시점): `article_body_len: post_id=about-acm/about-the-acm-organization 0자 (<100 — content selector 의심)`
- 이전 시도 = 다른 글 페이지 (`/about-the-acm-organization`) 본문 추출 실패

본 turn (SKILL.md §0b preflight 적용) 의 (b) 검사:
- `failed_at` 이후 `prompts/config_writer.system.txt` 변경 (uncommitted) 있음 → `register.py "<URL>"` 시도
- 결과: **✅ 자동 등록 통과 baseline 1건** (playwright_html strategy). 경고: `count_ballpark(1건 vs probe 후보 24)` + `matches_probe_first_article(probe first_article_url=/publications/about-publications 와 일치하는 글 없음)`

post_id = `code-of-ethics` (URL last segment), title = `ACM Code of Ethics and Professional Conduct`.

## 왜

`/code-of-ethics` = ACM 의 *단일 강령 문서* (board 아님). 그러나:
1. 학습된 blacklist ([[infra_learned_blacklist_2026-05-16]]) = `en.wikipedia.org/wiki/*` 같은 패턴 잡지만 `acm.org/*` 패턴 없음
2. single_article gate ([[infra_single_article_gate_2026-05-16]]) = nav-only 구조 or og:type=article 신호 잡으나 본 페이지는 *글 1개 = 진짜 글이긴 한* 모호한 케이스
3. count_ballpark 경고 = `1건 vs probe 후보 24` — *경고만, 거부 X*. probe 가 page 안 24 추가 anchor (related links 등) 봤으나 row_selector 가 1개만 매칭

→ 게이트 false negative — *board 인 척 등록*. 폴링은 형식상 OK (1건 baseline, "새 글" 0건 알림 영원히 X) — 사용자 영향은 *알림 X* 로 한정. 단 시스템 *부정확 상태*.

## 픽스

**현재 없음**. 본 case = evidence (게이트 강화 후보).

### 후속 후보 (별 작업)

[[infra_article_page_reject_3_2026-05-17]] 의 패턴 list 에 `acm.org/code-of-ethics`, `acm.org/about/*` 류 추가 — 단 가치 낮음 (단일 사이트). 또는:
- `count_ballpark` 경고가 *1건 vs ≥10건 probe 후보* 면 자동 거부 (강한 신호 — 본 case 의 1 vs 24).
- 별 작업 — vocab_candidate `single_article_gate_strengthen` (low) 누적 시 평가

## bench evidence

본 사이트는 arxiv 2601.06301 의 35 사이트 list *밖* (운영자 별 추가). [`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md) §1 (preflight 결과 — 7건 batch 중 1번) 에 추가 가치 (별 turn).

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only (registered-suspicious). 게이트 강화 candidate.
2. **이전 케이스 있나?** — [[host_techethics-ieee_about_bdcbf970]] (Cloudflare 차단 + single about page — 정책 거부). [[infra_article_page_reject_3_2026-05-17]] (single_article 패턴 list). 비슷 카테고리이나 본 case 는 *통과* 한 게 다름.
3. **재발 방지?** — `count_ballpark` 임계 강화 또는 acm.org 패턴 blacklist. 본 case 만으로 우선순위 낮음.
4. **자가 의심?** — preflight 1회. 본 URL 의 layout 변화 가능성. 또 *board 아닌 게* 진짜로 board 아닌지 검증 X (사용자가 의도적으로 등록 신청한 가능성).
5. **회귀 검증?** — register.py 의 자동 등록 통과 자체가 *baseline 1건 측정*. 다음 폴링 시 새 글 0건 알림 X = expected.
