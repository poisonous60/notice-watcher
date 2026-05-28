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
| **Figure 3** `/watch` call icicle | `id="harPipeline"` + `id="watchIcicle"` | `WATCH_CALL_TREE` const + `GITHUB_BASE`/`LANE_COLORS`/`LANE_LABELS` | `svg_watch_icicle` · `_render_icicle_node` · `_icicle_leaf_count` · `_icicle_truncate_path` · `_icicle_tooltip_html` |
| **Figure 4** Live HAR analysis | `id="harDetailFigure"` + `id="harSlugPicker"` + `.har-detail-panel` | `output/probe/<slug>/` artifacts | `pick_har_showcases` · `read_har_details` · `build_har_detail` · `render_har_detail_html` |
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

### 2c. Figure 3 — `/watch` call icicle

- **What**: 처음 보는 사이트를 `/watch` 한 순간부터 publish 까지 *어느 파일·함수가* 순서대로 도는지 보여주는 flame-icicle. 사용자 피드백 ("probe 안만 보임 — bot 진입부터 보고 싶다") 으로 funnel 폐기 + 전체 chain 으로 재설계 (2026-05-28).
- **Form**: top-down flame icicle. Y row = call depth (root 위), X = sequence. 부모 박스가 자식들의 X 범위를 spanning 한다 (flame-graph 룰).
- **Width 의미**: 박스 width = 그 노드 아래 leaf sub-step 수 (cascade shape — 시간 **아님**). 캡션 disclaimer 박혔다.
- **Lane 색** (process 경계): bot asyncio (`#3d737f` teal) / worker asyncio (`#6f7f52` olive) / register subprocess (`#8a6f4d` brown). 상단에 horizontal legend (swatch + 라벨). 박스 fill 색이 lane = 인라인 색인. lane 변화 = async hand-off (bot→worker) 또는 OS subprocess spawn (worker→subprocess).
- **분기**: 같은 grid 안 dashed border + tag chip (위) + fill-opacity 0.42 — `skip if already registered` / `fast-path: recognizer hit`.
- **Exit chip**: publish 박스 아래 작은 라벨 — `→ configs/<slug>.json + poll_state/<slug>.json` 으로 chain 종착지 명시.
- **Click → GitHub**: 각 박스 = `<a href="{GITHUB_BASE}/{file}#L{line}" target="_blank">` wrapping. 정확 라인 새 탭. `GITHUB_BASE = "https://github.com/poisonous60/notice-watcher/blob/main"`.
- **Hover → tooltip**: `data-tip-html` 에 `<strong>file</strong><br/>fn() · L<line><br/><em>branch-tag</em><br/>role` — 기존 Figure 4 의 `packetHoverTip` JS 핸들러 (4099 라인대) 가 그대로 catches. 라벨 truncation 의 손실분이 tooltip 으로 보강.
- **Truncation**: 박스 width 가 좁으면 `dir/file.py` → `file.py` (마지막 segment) → 추가 좁으면 trailing `…`. `_icicle_truncate_path` 가 처리.
- **Mobile**: SVG min-width 720px + container `overflow-x:auto` → 좁은 viewport 에서 가로 swipe. reflow 별 layout 안 만듦 (renderer 1개 유지).
- **Depth 4 rows × 56px + header 30 + footer 24 = SVG 278px high** (총 13 leaves). 기존 funnel 170px 보다 살짝 큼.
- **A11y**: `<svg role="img" aria-label="...">` 1개 (각 박스 tabindex X — 다중 tabstop 회피). 박스 자체는 SVG `<a>` 라 키보드 focus 받음. `:focus-visible` 시 stroke 강조.
- `WATCH_CALL_TREE` const = 손-maintain. 노드 = `{label, file, fn, line, lane, role, children?, branch?, exit_chip?}`. 코드 refactor 시 `line` 갱신 의무 (drift 허용 — best-effort anchor).
- **삭제됨** (2026-05-28): `svg_har_funnel`, `render_stage_panels`, `render_stage_flow_html`, `.funnel-*` / `.stage-panel-*` / `.step-*` CSS, funnel click/keyboard JS. `PROBE_PIPELINE` 상수 자체는 *데드 코드로 남음* (병렬 세션 fragment cache 작업이 잠시 참조 — 머지 후 정리 대상).
- 코드 = `svg_watch_icicle` ([scripts/generate_site.py:1306](../scripts/generate_site.py)), `WATCH_CALL_TREE` ([:49](../scripts/generate_site.py)), `_render_icicle_node` ([:1190](../scripts/generate_site.py)), `_icicle_truncate_path` ([:1160](../scripts/generate_site.py)), `_icicle_tooltip_html` ([:1175](../scripts/generate_site.py))

### 2d. Figure 4 — Live HAR analysis (dashboard parity)

- 자동 선택 최대 5 probe artifact 의 실제 분석 (dashboard `/probe-har` 페이지와 같은 신호를 공개용으로 축약)
- 구성:
  - **Picker** — option label 은 host-only. option value 는 `har-panel-N`. DOM 에 slug 를 노출하지 않는다.
  - **KPI strip** 4 셀 — entries / JSON-ish / xhr/fetch / HTTP 4xx/5xx
  - **Meta dl** — HAR mtime · verdict · config strategy · host label. probe host / first article host 는 `<details>` 안에 host-only 로 둔다.
  - **Content-type 분포** `<details>` (top 8)
  - **1 signal table** (`.har-signals`) — signal type / host / meta / evidence. 없는 raw signal type 은 `Not detected for this probe.` row 로 표시.
  - **raw signals (redacted)** `<details>`:
    - traffic_api_candidates — List JSON API 후보
    - traffic_article_body_candidates — Article body JSON 후보
    - rss_feed_urls — RSS / Atom
    - pagination_hints — pagination
    - audio_share_signal — audio share/player
    - digest allow-list summary — `engine.digest.build_digest(...)` 에서 공개 허용 row 만 추출
- **선택 로직** (`pick_har_showcases`, v5.1):
  1. 자격 floor: `configs/<slug>.json` 존재 + entries ≥ 50 + (json_mime_count ≥ 3 OR feed_candidates 존재)
  2. Score 계산 (entries band + JSON 강도 + feed + recent register success)
  3. 이전 선택 slug 가 자격 + score 가 max 와 ±1 이내면 sticky (재선택 노이즈 방지)
  4. tie-break 결정: score desc → band desc → json desc → slug asc
  5. 상위 5개를 `har-panel-0..4` 로 렌더
- **캐시** = `output/site/_har_detail.json` panel manifest. 직접 artifact + 코드 fingerprint:
  - `traffic.har`, `list.html`, `list_candidates.json`, `diagnosis.json`, `feed_candidates.json`, `environment.json`
  - `robots.json`, `sitemap.json`, `list.captured_headers.json`, `article_candidates.json`, `article_click.json`
  - `diagnosis.json.results[*].body_path` 파일
  - `configs/<slug>.json`, `probe/extract.py`, `engine/digest.py`, `engine/_mdr_candidates.py`, `probe/hydration.py`, `probe/paths.py`
  - 어느 입력 1개라도 바뀌면 invalidate → 재계산
- **Privacy** (ADR 0010 §17 + codex v4 §5, 강화):
  - 모든 URL → `_host_mask` (host 만 + `/ path hidden` 표시)
  - raw JSON → `_redact_json` 재귀: 민감 key 값 → `"[redacted]"`. 문자열 안 URL 패턴도 host-mask. 220 자 cap.
  - 공개 HTML 에 slug / `data-slug` / raw URL / recommended headers / captured headers / raw HTML sample path 를 두지 않는다.
  - digest 는 allow-list row 만 표에 올리고 raw dump 는 축약된 redacted subset 만 둔다.
- 코드 = `pick_har_showcases`, `read_har_details`, `build_har_detail`, `render_har_detail_html`, `_host_mask` · `_redact_json` ([scripts/generate_site.py](../scripts/generate_site.py))

## 3. 데이터 소스 (요약)

| Figure | 1차 데이터 | 폴백 | N100 가용 |
|---|---|---|---|
| Figure 1 | `output/poll_state/*.json` + `output/bot.sqlite3` jobs | — | ✓ |
| Figure 2 | `docs/cases/*.md` frontmatter + body | — (DB 패스 폐기) | ✓ (git 추적) |
| Figure 3 | `PROBE_PIPELINE` const (코드 박힘) | — | ✓ |
| Figure 4 | `output/probe/<slug>/*` + code fingerprints | placeholder panel | ✓ |
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
| Figure 4 picker | change | matching `.har-detail-panel` 1개만 visible |
| Figure 4 content-type | click summary | 분포 표 펼침 |
| Figure 4 raw signals | click summary | redacted JSON dump 펼침 |
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
| Plan v5.1 | `output/handoff/plan_har_v5.md` + review 반영 | Figure 3 flat rail, Figure 4 5-panel picker, digest allow-list, page-level privacy grep |

## 7. 미해결 / 후속

- Figure 3 stage 타이틀 → 관련 docs 앵커 링크 (`docs/config 기반 엔진 가이드.md` 등)
- 모바일 viewport — stage rail / har-signals 는 responsive 하도록 짰지만 실제 디바이스 테스트 0

## 8. 변경 절차

1. **dev 박스** 에서 `scripts/generate_site.py` 편집 (CLAUDE.md §1 — N100 에서 코드 편집 금지)
2. 로컬 `python scripts/generate_site.py` 로 dry run + `output/site/index.html` 브라우저 검수
3. ADR 0010 §17 grep — generated HTML 전체에서 raw URL / slug / header / cookie / selector / body 누출 0 확인
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
