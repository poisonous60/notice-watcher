# 2026-05-24 — tier1/tier2 prior-art follow-up v2

v1: [`docs/2026-05-24-tier1-tier2-followup.md`](2026-05-24-tier1-tier2-followup.md)

이번 문서의 질문은 하나다.

5개 Codex 실험 + sitemap pipeline audit 결과를 합치면, 지금 당장 production 에 넣을 prior-art / sitemap 개선이 있는가?

짧은 답: 거의 없다. 대부분 negative finding 이다.

입력 자료:

- [`experiments/sitemap-gate-bench/notes.md`](../experiments/sitemap-gate-bench/notes.md)
- [`experiments/sitemap-lastmod-bench/notes.md`](../experiments/sitemap-lastmod-bench/notes.md)
- [`experiments/sitemap-lastmod-bench/results.md`](../experiments/sitemap-lastmod-bench/results.md)
- [`experiments/prior-art-bench/notes_probe_vs_mdr.md`](../experiments/prior-art-bench/notes_probe_vs_mdr.md)
- [`experiments/prior-art-bench/notes_mdr_guarded.md`](../experiments/prior-art-bench/notes_mdr_guarded.md)
- [`experiments/autoscraper-triage/notes.md`](../experiments/autoscraper-triage/notes.md)
- [`experiments/prior-art-bench/matrix.md`](../experiments/prior-art-bench/matrix.md)
- [`experiments/prior-art-bench/notes_code_inspect_rss-proxy.md`](../experiments/prior-art-bench/notes_code_inspect_rss-proxy.md)

경로 검증:

| 경로 | 상태 | 메모 |
|---|---:|---|
| `docs/2026-05-24-tier1-tier2-followup.md` | 존재 | v1 tone/format 참조 |
| `probe/discover.py` | 존재 | `fetch_sitemaps` 본체 |
| `scripts/probe.py` | 존재 | Phase 6 에서 `fetch_sitemaps` 호출 |
| `engine/digest.py` | 존재 | `sitemap_candidates` digest 포함 |
| `prompts/config_writer.system.txt` | 존재 | LLM 에 `sitemap_candidates` 사용 지시 |
| `probe/extract.py` | 존재 | `_board_shape_check` 없음 |
| `probe/_heuristic.py` | 존재 | `_board_shape_check` 없음 |
| `scripts/register.py` | 존재 | `_board_shape_check` 실제 위치 |
| `experiments/prior-art-bench/notes_code_inspect_rss-proxy.md` | 존재 | v1 의 “없음” 상태와 달라짐 |
| `experiments/firecrawl-map-bench/` | 없음 | 이번 세션에서 삭제됨. Firecrawl `/map` drop 결정과 일치 |
| `docs/2026-05-24-tier1-tier2-followup-v2.md` | 신규 | 이 문서 |

---

## 1. TL;DR

Sitemap gate: ★. 구조상 gap 은 맞지만 이번 triage 배치에서는 in-scope 0건. gate 추가 단독으로 회복 증거 없음.

Sitemap lastmod: ★★. sampled 30 중 lastmod 10개(33.3%). 절감 배수는 커 보이나 stale/static page risk 가 커서 observe-only 후보.

MDR vs probe: ❌. MDR 단독 승리 cell 없음. `probe_extract` 와 같이 `skku_cse`만 성공. 나머지는 widget/nav/pagination/SPA.

MDR guarded: ❌/⚠. FP 는 줄였지만 전 사이트 n=0. `skku_cse` 정상 `articleNo` 까지 `url-pattern` 으로 과차단.

AutoScraper triage: ★. 0/8. 샘플 자체가 board-shape 복구 샘플이 아니었다. 단 prior-art bench 에서 `skku_cse` title 10개는 회수.

rss-proxy / Firecrawl: rss-proxy 는 XPath enumeration + scoring reference only. Firecrawl `/map` 은 free tier 1000 credit/month + 6 req/min 때문에 prod traffic 에 부적합.

---

## 2. Pipeline 전체 sitemap 활용 진단

### 2.1 현재 코드 경로

| 지점 | 코드 | 현재 상태 |
|---|---|---|
| sitemap fetch | `probe/discover.py:272` `fetch_sitemaps` | 이미 박힘 |
| robots seed | `probe/discover.py:299-307` | robots `Sitemap:` + 표준 경로 fallback |
| sitemap parse | `probe/discover.py:365` `_parse_sitemap_recursive` | 재귀 sitemapindex, gzip, cap |
| board-like scoring | `probe/discover.py:448` `_board_like_score` | URL keyword/id/depth score |
| probe 호출 | `scripts/probe.py:646-650` | Phase 6 에서 호출 |
| hard-login skip | `scripts/probe.py:638-645` | static hard login 은 빈 sitemap artifact |
| digest 포함 | `engine/digest.py:413` | `sitemap_candidates` 로 들어감 |
| prompt 지시 | `prompts/config_writer.system.txt:94` | LLM 에 board 아닌 URL 회복 후보로 사용 지시 |

`fetch_sitemaps` 의 output shape:

| key | 의미 |
|---|---|
| `page_url` | 입력 URL |
| `sitemap_urls_tried` | robots/표준 경로에서 실제 시도한 sitemap URL |
| `candidates` | `{url, score}` board-like 후보 |
| `stats` | sitemap_count/fetched/errors/out_total |
| `error` | fail-soft 오류 |

`_board_like_score` 기준:

| 신호 | 점수 |
|---|---:|
| `notice/bbs/board/news/article/post/공지/게시판/뉴스/글` keyword | +3 |
| `id/no/page/p/bid/cid/board` query | +2 |
| path 숫자 segment 3자리 이상 | +1 |
| path depth 1~3 | +1 |

### 2.2 `_board_shape_check` 위치 확인

| 파일 | `_board_shape_check` 포함 여부 | 메모 |
|---|---:|---|
| `probe/extract.py` | 없음 | 후보 추출/휴리스틱 신호 생산 |
| `probe/_heuristic.py` | 없음 | decorator registry 뿐 |
| `scripts/register.py` | 있음 | 실제 gate 구현 |

실제 위치:

| 함수 | 경로 | 관찰 |
|---|---|---|
| `_board_shape_check` | `scripts/register.py:574` | digest 기반 board gate |
| `n_feed` | `scripts/register.py:605` | `feed_candidates` 는 gate 신호 |
| sitemap 사용 | 없음 | `sitemap_candidates` 는 gate 신호에 포함되지 않음 |

현재 board-shape 통과 신호:

| 신호 | 현재 포함 |
|---|---:|
| `traffic_json_api_candidates` | ✅ |
| `inline_js_data_candidates` | ✅ |
| `hydration_list_candidates` | ✅ |
| same-host `html_repeating_patterns` | ✅ |
| same-host `first_article_url` | ✅ |
| same-host `clicked_resolved_url` | ✅ |
| `feed_candidates` | ✅ |
| `sitemap_candidates` | ❌ |

### 2.3 A-F 적용점

| ID | 적용점 | 현재 상태 | 측정 결과 | verdict |
|---|---|---|---|---|
| A | gate signal | 미실행 | `sitemap-gate-bench`: in-scope 0 | ❌ 지금 추가 금지 |
| B | reject advice | 미실행 | board_shape reject 문구에 sitemap 후보 안내 없음 | ★ 후보는 가능, 근거 부족 |
| C | bot UX | 미실행 | `bot/worker.py` 는 board_shape_fail 문구만 냄 | ★ 메시지 개선 후보, 자동 수락 아님 |
| D | lastmod polling | 측정만 | 30 sample 중 10 lastmod, 33.3% | ★★ observe-only |
| E | config regenerate | 이미 일부 박힘 | prompt 가 sitemap 후보 사용 지시 | ★ 유지. 재생성 자동화 근거는 약함 |
| F | adapter generalization | 미실행/손작성 사례만 | Canva/Salesforce config 는 sitemap 손활용 | ★ 손 config pattern reference |

### 2.4 A — gate signal

측정: [`experiments/sitemap-gate-bench/notes.md`](../experiments/sitemap-gate-bench/notes.md)

| 항목 | 값 |
|---|---:|
| triage queue 전체 | 40 |
| sitemap artifact 있는 entry | 8 |
| artifact 없는 entry | 32 |
| LOGIN/CFBOT/404/timeout drop | 4 |
| reject 사유 불일치 drop | 4 |
| threshold test 대상 | 0 |

threshold 결과:

| N | 신규 회복 | false accept |
|---:|---:|---:|
| 5 | 0 | 0 |
| 10 | 0 | 0 |
| 20 | 0 | 0 |

판정:

- gap 은 맞다.
- `feed_candidates` 는 gate 신호인데 `sitemap_candidates` 는 아니다.
- 하지만 이번 배치로는 회복 가능성 측정이 0이다.
- gate 만 풀면 LLM 으로 실패 시점만 이동할 수 있다.
- `list_candidates` enrichment 없이 gate 단독 추가는 ❌.

### 2.5 B — reject advice

현재 board_shape reject:

| 코드 | 상태 |
|---|---|
| `scripts/register.py:621` 근방 | “반복되는 글 링크/목록 API/피드 없음” |
| sitemap 후보 언급 | 없음 |
| sitemap score 기반 대체 URL 제안 | 없음 |

판정:

- 사용자에게 “sitemap 에 이런 후보가 보인다” 를 안내하는 UX 는 가능하다.
- 하지만 A 측정에서 회복 사례가 0이라 지금 넣으면 잡음일 수 있다.
- root marketing 쪽처럼 category suggestion 이 정교해진 뒤에 붙이는 편이 낫다.

### 2.6 C — bot UX

현재 bot 쪽:

| 코드 | 상태 |
|---|---|
| `bot/worker.py:320-338` | rc=3 board_shape fail 은 triage queue 오염 방지 |
| `bot/fail_taxonomy.py:292` | board_shape subkind |
| sitemap 후보 노출 | 없음 |

판정:

- bot UX 에 sitemap 후보를 보여주는 것은 자동 등록보다 안전하다.
- 단, 후보 URL 이 board 아닌 일반 page 일 수 있다.
- “이 후보로 다시 시도해보세요” 수준도 아직 과하다.
- “sitemap 후보는 있었지만 게시글 row 확인 전이라 자동 등록하지 않음” 정도가 한계.

### 2.7 D — lastmod polling

측정: [`experiments/sitemap-lastmod-bench/results.md`](../experiments/sitemap-lastmod-bench/results.md)

| 항목 | 값 |
|---|---:|
| sampled sites | 30 |
| sites with lastmod | 10 |
| coverage | 33.3% |
| mean savings factor | 1423.34x |

대표 rows:

| slug | lastmod | median age days | savings |
|---|---:|---:|---:|
| `host_aljazeera-com_root_2ac8d25a` | yes | 1.0 | 9.85x |
| `host_circleci-com_changelog_5a868561` | yes | 1.0 | 9.79x |
| `host_404media-co_root_9e71a06a` | yes | 221.4 | 2125.87x |
| `host_apnews-com_root_5ee5ebc1` | yes | 465.2 | 4466.10x |
| `host_datadoghq-com_blog_447ffb34` | yes | 0.0 | 5170.00x |

판정:

- 절감 배수 숫자는 큼.
- 하지만 mean 이 stale/static artifact 에 심하게 끌린다.
- `lastmod=0.0 days` 에서 5170x 같은 값은 정책 산식 검토 필요.
- production 적용은 observe-only + cap 필요.
- 전역 default 로 polling 을 늦추는 건 위험.

### 2.8 E/F — config regenerate / adapter generalization

| ID | 관찰 | 판정 |
|---|---|---|
| E | digest/prompt 에 `sitemap_candidates` 는 이미 들어감. sitemap 전용 retry branch 는 없음 | 유지. regenerate 품질은 미측정 |
| F | `configs/host_canva-com_whats-new_1e430553.json`, `configs/host_developer-sales_docs_1ee56ed9.json`, `configs/host_square-enix-com_jp_50b6a465.json` 에 손활용 사례 | 손 config reference. 자동 adapter 는 아직 아님 |

---

## 3. Bench 결과 (#1 + #2)

전체 matrix: [`experiments/prior-art-bench/matrix.md`](../experiments/prior-art-bench/matrix.md)

비교 행:

| row \ site | skku_cse | gamemeca | nexon_bluearchive | naver_cafe_gutterlife | arca_trickcal |
|---|---:|---:|---:|---:|---:|
| `mdr_unsupervised` | R=1.00 L=1.00 n=10/10 | R=0.00 L=0.00 n=10/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=7/10 | R=0.00 L=0.00 n=10/10 |
| `mdr_guarded` | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=0/10 |
| `probe_extract` | R=1.00 L=1.00 n=10/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=0/10 | R=0.00 L=0.00 n=1/10 | R=0.00 L=0.00 n=0/10 |

### 3.1 site별 승패

| site | winner | 이유 |
|---|---|---|
| `skku_cse` | `mdr_unsupervised` = `probe_extract` | 둘 다 10/10. `mdr_guarded` 는 과차단 |
| `gamemeca` | 없음 | MDR 은 인기게임/sidebar 10개. probe 는 no post. guarded 도 no post |
| `nexon_bluearchive` | 없음 | static HTML 에 목록 없음. SPA/API 문제 |
| `naver_cafe_gutterlife` | 없음 | MDR 은 top/nav 7개. probe 1개. 정답 없음 |
| `arca_trickcal` | 없음 | MDR 은 pagination 10개. guarded 는 제거 후 no post |

정량 결론:

| 질문 | 답 |
|---|---|
| MDR 이 probe_extract 를 이기는가 | 아니다 |
| probe_extract 가 MDR 을 이기는가 | 정답 점수로는 `skku_cse` 동률뿐 |
| mdr_guarded 가 회복하는가 | 아니다. 전부 R=0 |
| mdr_guarded 가 FP 를 줄이는가 | 예. 대신 recall 도 0 |

### 3.2 `mdr_guarded` JSON 검증

실제 파일 확인:

| 파일 | posts | error | notes 핵심 |
|---|---:|---:|---|
| `experiments/prior-art-bench/results/mdr_guarded/skku_cse__run1.json` | 0 | null | `url-pattern:1`, `nav-blacklist:6`, `text-density:2` |
| `experiments/prior-art-bench/results/mdr_guarded/gamemeca__run1.json` | 0 | null | `url-pattern:3`, `text-density:3`, `nav-blacklist:3`, `same-host:1` |
| `experiments/prior-art-bench/results/mdr_guarded/arca_trickcal__run1.json` | 0 | null | `numeric-only:1`, `nav-blacklist:4` |

`notes_mdr_guarded.md` 와의 차이:

| 항목 | note | 현재 disk truth | 판정 |
|---|---|---|---|
| run_all 네트워크 에러 | note 에 sandbox error run 언급 | 현재 JSON 은 HTTP 200, error null | ⚠ note 가 오래된 중간 상태 포함 |
| cached replay R=0 | note 에 R=0 | matrix/JSON 도 R=0 | 일치 |
| reject counts | note 와 JSON | 일치 | 사용 가능 |

따라서 v2 에서는 현재 `matrix.md` / JSON 을 우선한다.

### 3.3 왜 `mdr_guarded` 가 over-filter 하나

`skku_cse`:

| guard | count | 해석 |
|---|---:|---|
| `url-pattern` | 1 | 정상 게시글 목록 첫 후보를 제거 |
| `nav-blacklist` | 6 | header/nav 계열 제거 |
| `text-density` | 2 | 짧은 UI 제거 |

핵심 문제:

- SKKU 정상 URL 은 `articleNo=...` 형태.
- guard regex 는 `article=` 또는 `no=` 를 보지만 `articleNo=` 를 param 이름으로 인정하지 않는다.
- production `_article_url_score` 는 “3자리 이상 숫자” 를 더 넓게 가점한다.
- regex hard reject 가 production scoring 보다 약하다.

`gamemeca`:

| guard | count | 해석 |
|---|---:|---|
| `url-pattern` | 3 | 카테고리/비글 URL 제거 |
| `text-density` | 3 | 인기게임/sidebar 류 제거 |
| `nav-blacklist` | 3 | nav/menu 제거 |
| `same-host` | 1 | 외부/다른 host 다수 후보 제거 |

핵심 문제:

- 기존 MDR FP 는 제거됐다.
- 하지만 진짜 뉴스 리스트가 surviving candidate 로 오르지 않는다.
- “나쁜 것 버리기” 는 됐고 “좋은 것 고르기” 는 안 됐다.

`arca_trickcal`:

| guard | count | 해석 |
|---|---:|---|
| `numeric-only` | 1 | pagination `1 2 3 ...` 제거 |
| `nav-blacklist` | 4 | nav/aside 후보 제거 |

핵심 문제:

- pagination FP 제거는 성공.
- 이후 진짜 게시글 목록 후보가 MDR score 상위 surviving 후보로 남지 않는다.

### 3.4 prior-art verdict

| 후보 | 별점 | 판정 |
|---|---:|---|
| MDR raw | ★ | drop. 정답 단독 승리 없음 |
| MDR guarded bundle | ❌ | hard reject bundle 은 위험 |
| `numeric-only` guard | ★★ | 개별 signal 로는 가치 있음 |
| nav ancestor 확장 | ★★ | 기존 production 신호 보강 후보 |
| URL regex hard reject | ❌ | `articleNo` 같은 정상 URL 과차단 |
| text-density hard reject | ★ | signal 로만. gate 로는 위험 |

---

## 4. Triage 결과 (#3)

입력: [`experiments/autoscraper-triage/notes.md`](../experiments/autoscraper-triage/notes.md)

결과 파일:

| 파일 | 확인 |
|---|---:|
| `experiments/autoscraper-triage/results/host_cran-r-project-_root_b48d81b5.json` | 읽음 |
| `experiments/autoscraper-triage/results/host_firebase-google_support_1f0ed638.json` | 읽음 |
| `experiments/autoscraper-triage/results/host_akiba-souken-co_anime_7e88c174.json` | 읽음 |

### 4.1 0/8 요약

| 항목 | 값 |
|---|---:|
| sample count | 8 |
| complete config skeleton | 0 |
| URL selector filled | 0 |
| post_id filled | 0 |
| article content filled | 0 |
| usable board config | 0 |

샘플 구성:

| error_code | count | 해석 |
|---|---:|---|
| `F_OTHER` | 4 | board-shape reject 재측정 샘플 아님 |
| `X_404` | 4 | root/dead/detail 혼합. board-shape input 으로 부적합 |

### 4.2 JSON spot check

| slug | fetch | best_seed | URL sample | 판정 |
|---|---|---|---:|---|
| `host_cran-r-project-_root_b48d81b5` | saved list HTML | h1/page title | 0 | root landing. `noframes`/`h1` 잡음 |
| `host_firebase-google_support_1f0ed638` | 200 | null | 0 | release page title seed 로 rule 0 |
| `host_akiba-souken-co_anime_7e88c174` | DNS fail | null | 0 | autoscraper 전 fetch 실패 |

정직한 해석:

- AutoScraper 가 0/8 인 것은 맞다.
- 하지만 “AutoScraper 는 항상 무가치” 결론은 과하다.
- 샘플이 잘못됐다.
- X_404/F_OTHER/root/detail 은 게시판 row-shape 실험에 부적합하다.
- default seed 가 `og:title`/`title`/`h1` 이면 site name 또는 page heading 으로 빠진다.
- board row 내부 텍스트 seed 가 아니다.

### 4.3 prior-art bench 의 `autoscraper_seeded`

matrix:

| site | `autoscraper_seeded` | 해석 |
|---|---|---|
| `skku_cse` | R=0.00 L=0.00 n=10/10 | title 10개 회수, URL 없음 |
| `naver_cafe_gutterlife` | R=0.00 L=0.00 n=1/10 | seed 1개 + URL sample |
| 나머지 | R=0 | 회복 없음 |

실제 `skku_cse` JSON:

| 항목 | 값 |
|---|---|
| seed | 실제 post title |
| `n_rules` | 1 |
| `n_titles` | 10 |
| `n_urls` | 0 |
| posts | title 10개, URL 빈 문자열 |

판정:

- triage runner 자체는 “seed 가 실제 row title 이면 title cluster 를 찾을 수 있음” 을 보여준다.
- 하지만 URL/post_id 를 못 채우면 config 로는 실패다.
- 다음 측정은 board-shape failed + saved list HTML + 실제 첫 글 제목 seed 여야 한다.
- 지금 triage 결과는 `/watch` 자동 복구 근거가 아니다.

---

## 5. v1 의 #1~#6 정리

v1 section 5 후보:

| # | v1 작업 | status | 한 줄 이유 |
|---:|---|---|---|
| 1 | MDR vs `probe/extract.py` 3번째 bench row | done | `probe_extract` 행 추가. MDR 단독 win 없음 |
| 2 | MDR top-K 보조 점수 실험 | partial | `mdr_guarded` 로 guard 실험. 결과는 전부 R=0 |
| 3 | AutoScraper seed triage offline script | done/negative | runner+JSON 있음. 샘플 부적합으로 0/8 |
| 4 | REPS 문헌/용어 참고 정리 | deferred | 이번 turn 새 측정 없음. v1 reference-only 유지 |
| 5 | RSS-builder 코드 조사 재실행 | done | `notes_code_inspect_rss-proxy.md` 존재. XPath enumeration + scoring, GPLv3 |
| 6 | Firecrawl `/map` 검토 유지 | dropped | free tier 1000 credit/month + 6 req/min 으로 prod traffic 부적합. bench dir 삭제 |

보정:

| v1 statement | v2 correction |
|---|---|
| `notes_code_inspect_rss-proxy.md` 없음 | 현재 존재 |
| rss-proxy 판단 보류 | reference only 로 업데이트 |
| Firecrawl `/map` 후보 유지 | drop |
| MDR guard 가능성 | bundle 은 drop, 개별 guard 만 후보 |

---

## 6. 새 next-step 후보 (v2)

우선순위는 “실제 worth touching” 기준.

| # | 작업 | 효과 | 비용 | verdict |
|---:|---|---|---|---|
| 1 | board-shape rejection batch 만 모아 sitemap gate 재측정 | A 를 진짜로 판단 | 0.5일 | ★★ |
| 2 | sitemap gate + list enrichment 동시 실험 | gate-only 실패 시점 이동 방지 | 1일 | ★★ |
| 3 | lastmod observe-only artifact 설계 | polling 절감 후보를 안전하게 누적 | 1~2일 | ★★ |
| 4 | `mdr_guarded` URL guard 약화 후 재bench | `articleNo` 과차단 제거 확인 | 0.5일 | ★ |
| 5 | `numeric-only` 를 production debug signal 로만 추가 | pagination FP 설명력 상승 | 0.5일 | ★★ |
| 6 | AutoScraper triage 를 board-shape failed + real post seed 로 재측정 | 샘플 오류 제거 | 0.5~1일 | ★★ |
| 7 | AutoScraper URL/post_id extraction 보조 실험 | title-only 한계 확인 | 1일 | ★ |
| 8 | rss-proxy XPath enumeration clean-room prototype | link-list 후보 다양화 | 1~2일 prototype | ★ |
| 9 | Firecrawl `/map` 재검토 | 외부 API discovery | 하지 말 것 | ❌ |

---

## 7. 본 조사가 결론짓지 않은 것

본 조사가 결론짓지 않은 것:

- `sitemap_candidates` 를 `_board_shape_check` 에 넣으면 실제 등록률이 오르는지.
- board-shape reject batch 에서 sitemap 후보가 얼마나 자주 유효한지.
- sitemap 후보를 LLM 이 실제 config 로 잘 바꾸는지.
- sitemap `lastmod` 가 실제 신규 글 도착과 얼마나 상관 있는지.
- lastmod 기반 interval 을 늘렸을 때 missed notification 이 발생하는지.
- `mdr_guarded` 의 약한 URL scoring 버전이 `skku_cse` regression 을 없애는지.
- `numeric-only` debug signal 이 production triage 에 얼마나 도움이 되는지.
- AutoScraper 가 real post title seed 를 받으면 URL/post_id 까지 회복할 수 있는지.
- rss-proxy/feedless backend 실제 Kotlin scoring 이 local TS contract 와 얼마나 다른지.
- Firecrawl paid tier 를 쓰면 `/map` 이 운영적으로 타당한지. 이번 판단은 free tier 기준이다.

Negative scope:

| 범위 | 상태 |
|---|---|
| production code 수정 | 안 함 |
| `probe/`, `engine/`, `scripts/`, `bot/`, `prompts/`, `configs/` 수정 | 안 함 |
| benchmark 실행 | 안 함 |
| Codex subprocess 실행 | 안 함 |
| N100 배포 | 안 함 |
| Firecrawl bench 복구 | 안 함 |
| 없는 경로 silently propagate | 안 함. `experiments/firecrawl-map-bench/` 없음, rss-proxy 노트는 현재 존재로 정정 |

최종 결론:

| 항목 | 결론 |
|---|---|
| sitemap discovery | 이미 pipeline 에 들어와 있다 |
| sitemap gate | 아직 넣지 말 것 |
| sitemap lastmod | observe-only 후보 |
| MDR | drop |
| MDR guards | 개별 signal 만 일부 후보 |
| AutoScraper | board-shape input 으로 재측정 전까지 triage artifact 수준 |
| rss-proxy | reference only |
| Firecrawl `/map` | free tier 기준 drop |
