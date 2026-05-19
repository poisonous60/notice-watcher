---
slug: arca-live_trickcal_6703bf64
url: https://arca.live/b/trickcal
status: 🧩 손어댑터 (작동중, baseline 30, handwritten/ArcaLiveAdapter, playwright-stealth)
outcome: handcrafted
date: 2026-05-12
config_strategy: handwritten
adapters_changed: [ArcaLiveAdapter]
backfill: true
backfill_date: 2026-05-18
backfill_source: docs/2026-05-18-prior-art-followup-plan.md (Action #2)
vocab_candidates:
  - candidate: fingerprint_hide_required
    confidence: high
    evidence:
      - adapters/arca.py (playwright-stealth 사용 — `_open_browser` 의 `Stealth().apply_stealth_async`)
      - experiments/prior-art-bench/results/crawl4ai_llm/arca_trickcal__run1.json (R=0.20 — naive crawl4ai playwright 거의 차단)
      - experiments/prior-art-bench/results/llm_scraper/arca_trickcal__run1.json (R=0.70 — playwright + 3 anti-fingerprint 옵션 으로 통과)
      - experiments/prior-art-bench/results/manual_bs4/arca_trickcal__run1.json (R=0.00 — requests 403)
      - experiments/prior-art-bench/results/firecrawl_json/arca_trickcal__run1.json (R=0.00 — 페이지 접근은 OK, Notice rows 만)
    reasoning: "Cloudflare 가 naive httpx 100% 차단, naive playwright 도 차단. `webdriver=undefined` + `--disable-blink-features=AutomationControlled` + 정상 UA 의 3 옵션으로 70% 통과 — 즉 fingerprint hide *는* 필요, 풀 stealth 패키지가 *과연 필요한가* 는 별 점검 (followup-plan Action #5). closed vocab 의 `playwright_html` strategy 는 stealth 옵션 X — `request_signing_required` 와 다른 카테고리 (HTTP 헤더가 아니라 브라우저 fingerprint). 영향 후보 사이트: dcinside 일부, 기타 CF 보호 게임 위키. 후속 evidence [[host_reuters-com_root_9c8aa57a]] (Akamai bot manager — 같은 표면 증상). closed vocab 에 `list.stealth: \"minimal\" | \"full\" | null` 어휘 추가 가치. (2026-05-19 rename: `cf_fingerprint_hide_required` → `fingerprint_hide_required` — CDN-independent 으로 일반화. Akamai/Cloudflare/기타 bot-management 동일 처리.)"
    analysis_date: 2026-05-18
    deferred: true
  - candidate: response_branch_body
    confidence: not_applicable
    evidence:
      - adapters/arca.py:222-264 (`fetch_article` — status 분기 없음, `article` 요소 없으면 content_html=None 만 반환)
    reasoning: "ArcaLive 본문 fetch 는 응답 status 또는 type field 분기 없음. NaverCafe/DaumCafe (401/403 skip — `article.skip_status` 로 표현 가능) 와 Reddit (data.kind 분기 — 진짜 `response_branch_body` scope) 와 다른 패턴. 본 case 는 이 후보의 evidence 가 *아님* — 카운트 부풀리지 않기 위해 명시."
    analysis_date: 2026-05-18
    deferred: false
---

## 왜 손어댑터
ArcaLive (`arca.live/b/<채널>`) = Cloudflare 보호 + SSR 목록. `httpx` 정적 GET 은 어떤 헤더에서도 403 (UA 변경·Accept 헤더 추가해도 안 통함). Playwright 도 *naive* 로는 webdriver fingerprint 감지로 challenge — `playwright-stealth` 풀 패키지(또는 최소 3 옵션) 필요. 별도 JSON API 없음 (메인 페이지가 SSR 로 글 목록 직접 반환). 자동 파이프라인의 `playwright_html` strategy 는 stealth 어휘 없음 → 손어댑터로 갔다 (2026-05-12).

## 해결
손어댑터 `adapters/arca.py` `ArcaLiveAdapter` (`adapters/__init__.py` `__all__` 등록). `kwargs: {channel: "trickcal", include_notices: true}` (선택: `category` 탭 필터). Playwright Chromium (headless) + `playwright-stealth` (선택 import, 없으면 fallback) + `user_agent` 명시 + `locale: "ko-KR"` + `viewport 1280×900`. `page.goto(wait_until="domcontentloaded")` 후 `networkidle` 대기 (idle_timeout_ms=15000).

목록 = `https://arca.live/b/<channel>` (?p=<page>, ?category=<탭>). selector `a.vrow.column` (광고 = `.notice-service` 스킵, 채널 공지 = `.notice-board` — `include_notices` 따름). `href` 정규식 `/b/<channel>/<no>` 로 post_id 추출, 채널 불일치 무시. 행 안에서 `.title`·`.user-info`·`time[datetime]`·`.badge|.category` 파싱.

본문 = `https://arca.live/b/<channel>/<post_id>` GET. `article` 요소 안 `.article-body | .fr-view | .article-content | .content` (fallback chain) HTML 보관, 제목·작성자·시각 메타 추출. **status 또는 type field 분기 없음** — 본문 fetch 실패 (article 요소 X) 시 content_html=None 만 반환. 비공개 채널은 `state_path` 로 storage_state 재사용 (헤드풀 1회 로그인 후 state.json 저장).

폴링 영향 = baseline 30건 (trickcal 채널). `register.py --config configs/arca-live_trickcal_6703bf64.json` 으로 등록.

## 같은 플랫폼 자동 인식
2026-05-12 `engine/known_platforms.py` (현 `engine/recognizers/arca.py`) 에 `arca-live` 인식기 추가 — `arca.live/b/<channel>` 매칭, query `category=` 읽어 kwargs. 같은 플랫폼의 다른 채널은 `/watch https://arca.live/b/<channel>` 만으로 등록.

## bench evidence (2026-05-18 prior-art 조사)
[`experiments/prior-art-bench/matrix.md`](../../experiments/prior-art-bench/matrix.md) 중 arca_trickcal 행:

| 도구 | R | 비고 |
|---|---|---|
| manual_bs4 (requests + BS4) | 0.00 | 403 (CF) |
| crawl4ai_css (selector + crawl4ai playwright) | 0.00 | crawl4ai default 안 통과 |
| crawl4ai_llm (LLM + crawl4ai playwright) | 0.20 / 132s | 부분 통과 |
| **llm_scraper (Gemini + playwright + 3옵션)** | **0.70 / 53s** ⭐ | minimal anti-fingerprint 로 통과 |
| firecrawl_json | 0.00 | 페이지 접근 OK, prompt "recent" 인데 Notice rows (pinned 2024~2025) 만 추출 — prompt 조정 시 회복 가능 |

→ followup-plan Action #5 (`experiments/arca-stealth-bench/`) = prod adapter 의 풀 stealth 패키지가 *과한가* 별 점검. minimal 3옵션 충분하면 prod 단순화 (별 작업).

## 자가 점검 (5-질문 — backfill)
1. **어느 자리?** — backfill 만 (ADR 0003 §implementation #8). 코드 fix X. case .md 신규 작성 + `vocab_candidates` frontmatter.
2. **이전 케이스 있나?** — 같은 어댑터 (`ArcaLiveAdapter`) 의 다른 채널 case .md 없음 (prod 1개). 다른 stealth 필요 사이트 case .md 도 없음.
3. **재발 방지?** — `cf_fingerprint_hide_required` 후보 누적 시 vocab-ext SKILL 진입 (현재 1건, sub_threshold). 같은 후보 ≥3건 임계 시 closed vocab `list.stealth: "minimal"|"full"|null` 어휘 추가 평가.
4. **자가 의심?** — bench 1회 (`run1`) 만 — variance σ 측정 X (Cloudflare 시간대 변동 미반영). followup Action #5 가 variance 측정.
5. **회귀 검증?** — backfill 만 (코드 변경 X). `cases_index.py` INDEX 갱신 + `vocab-trigger --json` 출력에 ArcaLive 등장 확인.
