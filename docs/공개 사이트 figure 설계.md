# 공개 사이트 Figure 설계

`https://n100-noticewatcher.tail4a65b8.ts.net/` 에 떠 있는 정적 페이지(`scripts/generate_site.py` 가 10 분마다 N100 `notice-site.timer` 로 생성)에 박혀 있는 4 개 figure + 보조 섹션의 설계 기록. 사용자 피드백 4 회 반복 + codex 리뷰 2 회 거쳐 현재 모양으로 굳음. 운영(SSH/Tailscale/계정) 메모는 `docs/공개 현황 사이트.md`(gitignored). 정책 근거: ADR 0010.

## 1. 페이지 구성 (위 → 아래)

| 섹션 | 위치 | 출처 | 함수 |
|---|---|---|---|
| Header | top | `generated_at` | `render_html` 시작부 |
| Overview metrics | 4 셀 | `read_configs` · `read_poll_state` · `read_jobs` | `metric()` |
| **Figure 1** Radial scatter | `id="siteScatter"` | `output/poll_state/` + `output/bot.sqlite3` jobs | `svg_grouped_scatter` |
| **Figure 2** Case block grid + modal | `id="caseTimeline"` + `id="caseModal"` + `id="caseDB"` | `docs/cases/*.md` frontmatter + body | `read_case_records` · `svg_case_blocks` · `render_case_db` |
| Public Source Domains | host search list | `read_configs().hosts` + sites | inline in `render_html` |
| Recent Activity | table 20 row | `output/bot.sqlite3` jobs | `read_jobs` |
| **Figure 3** Probe pipeline funnel + stage panels | `id="harFunnel"` + 5×`stage-panel` | `PROBE_PIPELINE` const | `svg_har_funnel` · `render_stage_panels` · `render_stage_flow_html` |
| Lane summary | configs 카운트 | `configs/*.json` `_recognized_platform` 마커 | `read_har_lane_counts` · `render_lane_summary` |
| **Figure 4** Live HAR analysis | `id="harDetailFigure"` | `output/probe/<slug>/` artifacts | `pick_har_showcase` · `build_har_detail` · `render_har_detail_html` |
| HAR field anatomy | 5-row table | static doc | `render_har_anatomy_static` |
| Footer | bottom | — | inline |

## 2. Figure 별 상세

### 2a. Figure 1 — Radial scatter (기존 유지)

- 평가한 모든 URL 1 dot. 색 = fetch strategy (static HTML / JSON API / headless browser / custom adapter) 또는 outcome (content / blocked / dead / bug)
- Inner disc = watched boards (host-clustered sunflower + Lloyd 완화)
- Outer rings = content / blocked / dead / bug (necklace 배치)
- Hover dot = tooltip (host + path + strategy + status). Click = URL 새 탭.
- viewBox 920 × 840
- 코드 = `svg_grouped_scatter` ([scripts/generate_site.py:522](../scripts/generate_site.py))

### 2b. Figure 2 — Case block grid + modal

- "엔진 + 위에 덧붙는 고철" 메타포 (사용자 요청, 2026-05-28)
- 매 case = `docs/cases/*.md` 파일 1개 = 4×4 px 사각형
- x = 일자 (column), y = baseline 위로 stack
- 색 = fix-layer bucket (CONTEXT.md "추론 개선" 어휘):
  - F · recognizer / platform (`#3d737f` teal)
  - C · probe heuristic (`#8a6f4d` brown)
  - A · prompt / agentic (`#7b5c8c` purple)
  - B/D/E · engine·writer·validate (`#6f7f52` olive)
  - no-change (`#c8c0ad` light)
- **굵은 테두리** = `outcome: improved` (시스템이 그 패턴 자동 처리하게 됨)
- 점선 vertical = pipeline milestone (`EVENT_ANNOTATIONS` const)
- **클릭** → modal (제목 + first paragraph + GitHub md 링크)
- 키보드 = Tab → Enter/Space (`tabindex="0" role="button"`)
- Esc / backdrop click 닫음
- viewBox 920 × 640, block_size 11px gap 2px
- 데이터 dev-box DB `output/cases.sqlite3` 대신 `docs/cases/*.md` frontmatter 직접 파싱 (N100 에 DB 없음 — codex 리뷰 v2 §1 fix)
- bucket 우선순위 F > C > A > B/D/E 첫-매치, `config`/`adapter` → B/D/E (`_fix_layer_bucket`)
- 코드 = `svg_case_blocks` · `render_case_db` ([scripts/generate_site.py:857](../scripts/generate_site.py), [:992](../scripts/generate_site.py))

### 2c. Figure 3 — Probe pipeline funnel + stage panels

- 5 단계 가로 funnel (Step 1 ~ 5), 박스 안 = "Step N / Title / tagline"
- **숫자 없음** (사용자 피드백 — aggregate count "Probe runs 4878" 류 의미 없다)
- 박스 클릭 → 해당 stage panel 펼침 (다른 panel hidden)
- 키보드 a11y = `tabindex="0" role="button" aria-controls aria-expanded`
- 5 stage:
  1. **Probe fetches** (static + browser) — `scripts/probe.py main`, `probe/fetch_static.py fetch`, `probe/fetch_headless.py fetch_with_capture`
  2. **Capture HAR** (network log + HTML) — `record_har_path on new_context`, `traffic.har`, `list.html`, `environment.json`
  3. **Inspect entries** (data calls, not assets) — `json.loads(har)`, `_entry_resource_type`, `_AD_TRACKER_RE` filter
  4. **Match signals** (APIs · feeds · pages · platforms) — `traffic_api_candidates`, `traffic_article_body_candidates`, `rss_feed_urls`, `pagination_hints`, `detect_*_platform`
  5. **Choose path** (digest · recognizer · writer) — `_try_known_platform`, `build_digest`, probe-marker platform config, `auto: api_loop_once → agentic`, `_register_built_config`
- stage panel 안 = `<ol class="stage-flow"><li class="step-card">` (flexbox `justify-content: center` + `flex: 0 1 200px` — orphan card 가운데 정렬 자동, codex v4 리뷰 §6 fix)
- 화살표 사이 박스 없음 (codex v4 §7 — `:nth-child` 화살표 룰 wrap 깨짐)
- `PROBE_PIPELINE` const = 손-maintain (probe 코드 refactor 시 갱신 의무)
- 코드 = `svg_har_funnel` ([scripts/generate_site.py:1071](../scripts/generate_site.py)), `PROBE_PIPELINE` ([:31](../scripts/generate_site.py)), `render_stage_panels` ([:1158](../scripts/generate_site.py)), `render_stage_flow_html` ([:1134](../scripts/generate_site.py))

### 2d. Figure 4 — Live HAR analysis (dashboard parity)

- 자동 선택 1 probe artifact 의 실제 분석 (dashboard `/probe-har` 페이지와 같은 구조)
- 구성:
  - **KPI strip** 4 셀 — entries / JSON-ish / xhr/fetch / HTTP 4xx/5xx
  - **Meta dl** — slug · HAR file 이름 + mtime · probe host · first article host · diagnosis verdict · config strategy
  - **Content-type 분포** `<details>` (top 8)
  - **5 signal section** (각각 title + 소스 함수명 + 표 + 접힌 raw JSON):
    - traffic_api_candidates — List JSON API 후보
    - traffic_article_body_candidates — Article body JSON 후보
    - rss_feed_urls — RSS / Atom
    - pagination_hints — pagination
    - audio_share_signal — audio share/player
  - **list_candidates artifact** — `output/probe/<slug>/list_candidates.json` 키 목록 (key/type/count/preview)
- **선택 로직** (`pick_har_showcase`, codex v4 §1):
  1. 자격 floor: `configs/<slug>.json` 존재 + entries ≥ 50 + (json_mime_count ≥ 3 OR feed_candidates 존재)
  2. Score 계산 (entries band + JSON 강도 + feed + recent register success)
  3. 이전 선택 slug 가 자격 + score 가 max 와 ±1 이내면 sticky (재선택 노이즈 방지)
  4. tie-break 결정: score desc → band desc → json desc → slug asc
- **캐시** = `output/site/_har_detail.json` manifest 키 (codex v4 §2 fix). 키 = 7 파일 `{path,size,mtime_ns}`:
  - `traffic.har`, `list.html`, `list_candidates.json`, `diagnosis.json`, `feed_candidates.json`, `environment.json`, `configs/<slug>.json`, `probe/extract.py`
  - 어느 입력 1개라도 바뀌면 invalidate → 재계산
- **Privacy** (ADR 0010 §17 + codex v4 §5, 강화):
  - 모든 URL → `_host_mask` (host 만 + `/ path hidden` 표시)
  - raw JSON → `_redact_json` 재귀: keys `url / sample_url / evidence_url / url_template / selector / css_selector / xpath / headers / cookies / set-cookie / request_body_text / body / sample / html` 의 값 → `"[redacted]"`. URL string 패턴 → host-mask. 220 자 cap.
  - 5 row cap per section + "+N more" 표시
  - `digest` artifact 의도적 제외 (`engine.digest` 의존성 + recommended headers 노출 회피)
- 코드 = `pick_har_showcase` ([scripts/generate_site.py:1421](../scripts/generate_site.py)), `build_har_detail` ([:1547](../scripts/generate_site.py)), `render_har_detail_html` ([:1701](../scripts/generate_site.py)), `_host_mask` · `_redact_json` ([:1240](../scripts/generate_site.py))

### 2e. Lane summary

- `<ul class="lane-rows"><li class="lane-row">` × 2 — `.lane-row` 클래스로 acceptance grep 모호성 제거 (codex v4 §10)
- "No platform marker" / "Platform-marked" 분리, strategy chip pill
- Footnote: marker = `_recognized_platform`. unmarked = HAR / static / RSS / manual / legacy 다 섞임 — provenance field 박혀야 정확히 분리 가능
- "HAR-driven" 라벨 폐기 (codex v3 §7 — no-marker 269/306 의 대부분이 httpx_html static, HAR 유래 아님)
- 코드 = `render_lane_summary` ([scripts/generate_site.py:1208](../scripts/generate_site.py)), `read_har_lane_counts` ([:1033](../scripts/generate_site.py))

### 2f. HAR field anatomy (static)

- 5 행 — `request.url` · `request.method` · `response.status` · `response.headers.content-type` · `response.content.size`
- 라이브 샘플 값 없음 (ADR 0010 §17 — URL/header/body content 노출 회피)
- 코드 = `render_har_anatomy_static` ([scripts/generate_site.py:1180](../scripts/generate_site.py))

## 3. 데이터 소스 (요약)

| Figure | 1차 데이터 | 폴백 | N100 가용 |
|---|---|---|---|
| Figure 1 | `output/poll_state/*.json` + `output/bot.sqlite3` jobs | — | ✓ |
| Figure 2 | `docs/cases/*.md` frontmatter + body | — (DB 패스 폐기) | ✓ (git 추적) |
| Figure 3 | `PROBE_PIPELINE` const (코드 박힘) | — | ✓ |
| Figure 4 | `output/probe/<slug>/*` 7 file | placeholder | ✓ |
| Lane summary | `configs/*.json` `_recognized_platform` | — | ✓ |
| Recent Activity | `output/bot.sqlite3` jobs | — | ✓ |

## 4. 인터랙션 일람

| 위치 | 트리거 | 동작 |
|---|---|---|
| Figure 1 dot | hover | tooltip (host + path + strategy + status) + 같은 strategy dot dim |
| Figure 1 dot | click | URL 새 탭 |
| Figure 2 block | hover | tooltip (slug + bucket) |
| Figure 2 block | click / Enter / Space | modal — case 제목 + first paragraph + GitHub md 링크 |
| Figure 2 modal | Esc / backdrop / × | 닫음 |
| Figure 2 legend | click | bucket band on/off |
| Figure 2 annotation marker | hover | tooltip — 그날 landed 인프라 변경 설명 |
| Figure 3 funnel box | click / Enter / Space | stage panel 펼침 (다른 panel 접힘, aria-expanded toggle) |
| Figure 4 content-type | click summary | 분포 표 펼침 |
| Figure 4 raw JSON | click summary | redacted JSON dump 펼침 |
| Domain search input | type | host list filter |

## 5. 성능

| 영역 | dev 박스 | N100 | 한계 |
|---|---|---|---|
| 전체 cold (모든 cache 없음) | ≈ 1.1s | ≈ 15s | < 30s (10 분 타이머) |
| 전체 warm (cache hit) | ≈ 1.0s | ≈ 5s | — |
| Figure 4 — manifest 키 invalidate 시 | 0.5s ~ 1s | 1 ~ 3s | 5s |
| 메모리 peak (N100) | — | 130 MB | < 500 MB |

이전 v1 (aggregate funnel + per-slug cache) = N100 60s cold + 3.3GB peak. v4 에서 HAR aggregate 폐기 + 1 슬러그 detail 만 처리 → 75% 감소.

## 6. 설계 history (Plan + codex review 누적)

| 단계 | 파일 | 결정 |
|---|---|---|
| Plan v1 | `output/handoff/plan_public_site_figures.md` | Figure 2 stacked area (cum case count, fix layer drift) + Figure 3 funnel + 단순 anatomy |
| codex v1 review | `output/handoff/plan_public_site_figures_review.md` | REVISE — cases.sqlite3 dev-only / aggregate cache stale / screenshot privacy / acceptance gaps |
| Plan v2 | `output/handoff/plan_public_site_figures_v2.md` | frontmatter 폴백 / content-key cache / no screenshot / 2-panel stacked area / Lane A/B 분리 |
| (사용자) | 메타포 변경 | "엔진 + 고철 덧붙기" → 사각형 grid (개별 case 블록) |
| v2.5 ship | commit `cfad4b7` | Figure 2 = stacked area (legacy) |
| v3 ship | commit `97576d4` → `52ac92b` | Figure 2 = case block grid + modal |
| Plan v3 (HAR) | `output/handoff/plan_har_v3.md` | clickable funnel + per-stage file-flow + lane summary + anatomy. dashboard-style HAR detail 폐기 |
| codex v3 review | `output/handoff/plan_har_v3_review.md` | REVISE — 파일/함수 이름 다수 오류 / 2-row layout 불가 / Lane A/B 라벨 오류 / 단계 경계 오류 |
| v3 ship | commit `2b86ede` | Figure 3 = funnel(숫자 없음) + 5 stage panel + step-card SVG. 이름 모두 fix. |
| (사용자) | dashboard HAR fields 누락 + UI 정렬 | Figure 4 추가 + step-card HTML 화 + section-gap scope |
| Plan v4 | `output/handoff/plan_har_v4.md` | Figure 4 (dashboard parity) + flexbox step-card + scoped section-gap |
| codex v4 review | `output/handoff/plan_har_v4_review.md` | REVISE — cache key narrow / privacy parity 불충분 / grid 1fr orphan 안 가운데 / `section + section` global 너무 넓음 |
| v4 ship | commit `fd695a8` | Figure 4 host-masked + manifest cache + flex card + scoped gap |

## 7. 미해결 / 후속

- `_generation_source` 또는 `_har_signal` 마커를 config 작성 시점에 박으면 Lane A / B 정확히 분리 가능 (현재 "no platform marker" 모호함)
- Figure 3 stage 타이틀 → 관련 docs 앵커 링크 (`docs/config 기반 엔진 가이드.md` 등)
- `digest` artifact section 복원 가능 — `engine.digest.build_digest` 가벼운 imports 만 쓰도록 분리 후
- 모바일 viewport — step-card / har-section-table / lane-chips 다 flex/grid 박혀 자동 wrap 가능하나 실제 디바이스 테스트 0

## 8. 변경 절차

1. **dev 박스** 에서 `scripts/generate_site.py` 편집 (CLAUDE.md §1 — N100 에서 코드 편집 금지)
2. 로컬 `python scripts/generate_site.py` 로 dry run + `output/site/index.html` 브라우저 검수
3. ADR 0010 §17 grep — Figure 4 안 raw URL / header / cookie / selector / body 누출 0 확인
4. `git add scripts/generate_site.py && git commit -m "..." && git push origin main`
5. pre-push hook 이 `probe_smoke --stage 3 --stage 5` 자동 검증
6. `ssh aaaa@n100-noticewatcher 'bash ~/notice-watcher/scripts/n100_deploy.sh'` (ADR 0018 — `notice-poll.timer` atomic stop/start wrapper)
7. `systemctl --user start notice-site.service` 로 즉시 한 사이클 (안 돌리면 10 분 타이머 사이클 기다림)
8. `curl -sI https://n100-noticewatcher.tail4a65b8.ts.net/` 200 확인 + 브라우저 hard-refresh 검수

`PROBE_PIPELINE` const 갱신 시 — probe 코드 (특히 `scripts/probe.py`, `probe/fetch_*.py`, `probe/extract.py`, `engine/digest.py`, `scripts/register.py`) refactor 가 있으면 파일/함수 이름 동기화. 동기 안 하면 외부인이 잘못된 안내 받음.

## 9. 관련 ADR / 문서

- **ADR 0010** `docs/adr/0010-public-status-site-via-tailscale-funnel.md` — 공개 사이트 분리 / 익명화 화이트리스트 / Tailscale Funnel 서빙
- **ADR 0017** `docs/adr/0017-poll-notify-runs-tracking.md` — `bot.sqlite3` jobs 스키마 (Figure 1 + Recent Activity)
- **ADR 0018** `docs/adr/0018-cron-commit-race-guard.md` — N100 deploy wrapper (`scripts/n100_deploy.sh`)
- `docs/공개 현황 사이트.md` — 운영자 메모 (gitignored — 접속/관리 절차, N100 unit 경로 등)
- `CONTEXT.md` — 어휘 (fix-layer / "추론 개선" / handcrafted / improved / "새 글 올라오는 곳" 등 Figure 2 색 의미의 source-of-truth)
