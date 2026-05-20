---
slug: infra_gate_false_positive_fixes_2026-05-20
url: (인프라 — 3 게이트 false-positive fix, 사이트 N/A)
status: ✅ 자동 (article_page_reject + meta_diverging + multi_host_hub 3개 fix)
outcome: improved
date: 2026-05-20
fix_layer: C+F
failure_keys: [recognizer_article_page_reject, meta_diverging, multi_host_hub]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: [engine/recognizers/article_page_reject.py, scripts/register.py, probe/extract.py, tests/recognizers/test_article_page_reject.py, tests/probe_heuristics/test_list_row_external_host.py]
tags: [gate-fix, false-positive, batch-2026-05-20]
---

## 무엇이 일어났나

catalog 2026-05-20 batch 의 18 gate_reject 안에 3 false-positive 패턴 — 사용자가 들어가보니 *진짜 게시판* 인데 거부:

1. **`recognizer:article_page_reject`** (3건) — ja/ko Wikipedia Special:RecentChanges, en Wikipedia Main_Page
   - ja: `https://ja.wikipedia.org/wiki/特別:最近の更新` (RecentChanges)
   - ko: `https://ko.wikipedia.org/wiki/특수:최근바뀜` (RecentChanges)
   - en: `https://en.wikipedia.org/wiki/Main_Page` (메인 — featured/news 섹션 폴링 가능)
   - 원인: negative look-ahead 에 영어 외 lang 의 Special 별명 (`특수:`/`特別:`) 누락 + URL-encoded 형 (`%ED%8A%B9%EC%88%98`/`%E7%89%B9%E5%88%A5`) 누락. 기존 `특수기능:` 토큰은 *오타* (한국어 위키 namespace 는 `특수:`).

2. **`meta_diverging`** (1건) — 게임메카 `https://www.gamemeca.com/news.php`
   - probe: input first-segment=`news.php` vs first_article=`view.php` — 다르다고 single-article 판정.
   - 원인: PHP/ASP/JSP-routed 사이트는 *한 .php=list*, *다른 .php=article* 이 정상 패턴. path 비교 무의미.

3. **`multi_host_hub`** (1건) — 디시인사이드 m. 메이플 갤 `https://m.dcinside.com/board/maple`
   - probe row_external_host: `unique_external_hosts=['gall.dcinside.com', 'game.dcinside.com', 'www.dcinside.com']` 3건, ratio=1.0 → multi_host_hub=True.
   - 원인: 외부 호스트가 *모두 같은 etld+1* (`dcinside.com`) 의 sibling subdomain — 인프라 분리, 같은 사이트. tistory hub (다른 user subdomain + 다른 etld+1 섞임) 와 분리되지 않음.

## 무엇을 바꿨나

### 1. `engine/recognizers/article_page_reject.py` — Wikipedia look-ahead 확장
- 추가 토큰: `특수:`, `特別:`, `特别:`, `分类:`, `分類:`, `Main_Page`, `대문`, `메인_화면`, `메인페이지`, `메인_페이지`, `メインページ`.
- URL-encoded: `%ED%8A%B9%EC%88%98`, `%E7%89%B9%E5%88%A5`, `%E7%89%B9%E5%88%AB`, `%EB%8C%80%EB%AC%B8`, `%E3%83%A1%E3%82%A4%E3%83%B3%E3%83%9A%E3%83%BC%E3%82%B8`.
- 기존 `특수기능:` 보존 (legacy compat).

### 2. `scripts/register.py:_meta_article_diverging_check` — router-file 가드
- `_ROUTER_FILE_EXT_RE = re.compile(r"\.(php|asp|aspx|jsp|cgi|do)$", re.I)`.
- 둘 다 (inp/fau) router-file extension 매칭이면 path 비교 skip → 게이트 통과.

### 3. `probe/extract.py:list_row_external_host` — etld+1 sibling 가드
- `_registered_domain(host)` helper 추가 (tldextract 사용, fallback last-2-segments).
- `multi_host_hub` 판정: 기존 (unique_external_hosts ≥ 3 AND ratio ≥ 0.95) **AND** `not same_etld_only` (모든 외부 host 가 base 와 같은 etld+1 인 경우 제외).
- output 에 `base_registered_domain` 필드 추가.

### 4. tests + smoke
- `test_article_page_reject.py` 3 신규 fixture (ko/ja Special URL-encoded + en Main_Page).
- `test_list_row_external_host.py` 2 신규 fixture (sibling subdomain negative + mixed etld positive).
- `probe_smoke --stage 3 --stage 5` 423 PASS.

## 트랙 B 검토

- 모두 *probe 휴리스틱 / recognizer pattern* 영역. 트랙 B 본질.
- 트랙 A (사용자 향) = 같은 변경 — false-positive 거부됐던 3 entry 가 자동 재시도 시 통과.

## 회귀 가드
- tistory hub 검증 보존 (test 9 `multi_host_hub_tistory_positive` PASS — `.tistory.com` × 2 + `daum.net` 1 → 여전히 hub).
- 진짜 Wikipedia article 거부 보존 (test gap_check_wiki_en/ko PASS).
- 한 가지 .php 패턴 (board 페이지 자체가 og:type=article 박은 omate 류) 은 first-segment 동일 → 기존 가드 그대로 통과.
