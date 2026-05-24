---
session: podcast batch 잔여 16건 처리 (2026-05-24)
skill: hand-config (codex 위임 모드)
outcome_summary: 49 + 1 (handcrafted radiolab) + 2 (handcrafted thisamericanlife/oxide) + 6 (post-fix-cleanup 자동 cleanup) registered. 4 RSS slug "영구 layer 박힘 + no_change" 처리 (정정 후 thisamericanlife/oxide 는 handcrafted 등록 — 즉 *원래는 수동 config 트랙 진입 했어야*). 3 cap_blocked Later defer + 2 gate-fail park (cbs 빈 feed / dotnetrocks Blazor SPA).
date: 2026-05-24
tags: [retro, process, hand-config, pipeline-improvement]
---

# 세션 retro — podcast batch 잔여 처리

## 1. 일어난 일 (시간 순)

1. triage pull → 15 slug, podcast batch 8 gen_fail + 7 다른 batch.
2. 8 gen_fail 분류 + screen-out:
   - 3 cap_blocked (azure timeout / apple SPA timeout / bloomberg 403) → triage_later 박기.
   - 5 작업 가능 분류: cbs/dotnetrocks/thisamericanlife/oxide (RSS 일반화 후보) + radiolab (playwright selector handcrafted).
3. 사용자에게 분포 보고 + 청크 분할 결정 받음 (2 청크 worktree 병렬).
4. 청크 A (RSS 일반화 4 slug) + 청크 B (radiolab) codex 위임 launch. 14분 drain.
5. 청크 A·B 둘 다 merge. probe_smoke PASS, cases_index regen. commit + push + N100 pull + bot restart.
6. N100 후속 검증: radiolab baseline 12건 ✅. **4 RSS slug 다 자동 회복 X** (LLM 3회 retry 동일 fail).
7. 4 RSS slug case_log outcome=no_change 박고 worktree 정리, post-fix-cleanup (6 slug 자동 cleanup) 호출.
8. *세션 끝* 으로 보고했는데 — **사용자 정정**: "8 gen_fail 왜 남아있냐? §2e 수동 config 트랙 남아있다".
9. cbs/oxide/dotnetrocks/thisamericanlife 각 사이트 *진짜 RSS endpoint* 직접 fetch 확인:
   - cbs: RSS XML 200 OK 지만 **item 0건 빈 feed**.
   - dotnetrocks: `/RSS` path 가 **Blazor SPA HTML** (RSS XML 아님).
   - thisamericanlife: 완벽한 RSS XML — 수동 config 가능.
   - oxide: `rss.xml` URL 자체가 **Transistor HTML SPA**, 진짜 RSS = `feeds.transistor.fm/oxide-and-friends` (link rel alternate).
10. cbs + dotnetrocks → **gate-fail park** (빈/가짜 RSS, 분류 오판).
11. thisamericanlife + oxide → **수동 config** 작성. dev box validate + smoke + register baseline + N100 pull + register 둘 다 ✅.
12. **사용자 추가 정정**: oxide config 의 `list.url_template` 이 *제출 URL 의 host* 와 다른 host (feeds.transistor.fm). 잘못된 링크인지 *직접 검증 안 하고* 단정한 거 지적 받음. 검증 결과: oxide.computer/podcast/rss.xml = 사람 보기엔 podcast 게시판 (Transistor HTML 렌더), URL 자체는 잘못 X. config 그대로 OK 결정.
13. **사용자 또 다른 지적**: "audio_share_host_detected 변수명 지엽적. 일반화 맞아?" — 청크 A 의 휴리스틱이 `_AUDIO_SHARE_HOST_SUFFIXES` 9 host hardcode. 구조 신호 X. → 청크 C (구조 일반화) codex 위임 launch.

## 2. 어떻게 했어야 했는데 안 했나

### β1. §2e 수동 config 트랙 *조기 종료*

**잘못**: LLM 자동 회복 X 보고 `outcome=no_change escalate` 으로 4 slug 처리 끝냈다. hand-config 본질 = LLM 못 풀면 사람(또는 codex)이 *수동 config* 박는 것. SKILL.md §2 분기는 2a→2b→2c→2d→2e 순서로 따져 첫 매칭, *전부 못 풀면* §2e (handwritten) 가 정답. 내가 §2c (probe 휴리스틱) + §2a/2d (recognizer/probe) layer 박은 것 만으로 *끝났다* 가정.

**올바른 흐름**: 
- 청크 A merge 후 N100 register 검증해서 4 slug 다 fail → 그 시점에 *각 slug 별 §2e 진입* (probe artifact 분석 + 진짜 RSS endpoint 확인 + handcrafted config).
- 자동 회복 X 자체가 §2e 트리거.

### β2. 빈/가짜 RSS 분류 누락

**잘못**: cbs RSS 200 OK = 진짜 게시판 으로 가정. probe `feed_candidates` 가 `well-known-path` source 로 발견했지만 *내용* (item 수) 검증 안 함. dotnetrocks `/RSS` = `input-url-feed-path` (URL 추측만, RSS XML 검증 0) — 이거 *실제 검증 됐는지* 안 따짐.

**올바른 흐름**:
- probe `feed_candidates` 의 `source` 가 `well-known-path` 또는 `input-url-feed-path` 면 *RSS XML 직접 fetch + item 수 확인* 필요.
- 빈 feed (item=0) 또는 HTML 응답 (Blazor SPA) → **gate-fail park** (분류 오판 — 사실 비-게시판).
- SKILL.md §0b-2 screen-out 의 P1 (content-as-list) / P2 (not-found shell) 옆에 **P3 (empty/fake feed)** 카테고리 추가 가능.

### β3. 단정적 결론 (검증 안 하고 "맞다")

**잘못**: 청크 A no_change 박은 후 *세션 끝* 으로 보고. oxide config 손-작성 시 "잘못된 링크" 단정. 사용자 매번 정정해줘야 했음.

**올바른 흐름**:
- 사용자 보고 *전에* 각 slug 의 *사람-인지* 상태 검증 (브라우저로 열면 무엇이 보이나? 게시판인가 단일글인가 빈 페이지인가).
- "잘못" 결론 박기 전에 cross-check 한 번 더 (curl raw + browser 시뮬레이션 + 진짜 feed URL).

### β4. 청크 A task 작성 시 *list hardcode* 박아줌

**잘못**: 청크 A task 의 영역 C 에서 내가 직접
> RSS item 의 `<link>` 가 list host 와 다른 *audio share host* (`*.transistor.fm`, `libsyn.com`, `simplecast.com`, `art19.com`, `megaphone.fm`, `anchor.fm`, `podbean.com`, `podtrac.com` 등) 면 ...

박아 codex 가 그대로 `_AUDIO_SHARE_HOST_SUFFIXES` 9 host hardcode. **구조 신호** 박으라고 task 에 명시 안 함.

**올바른 흐름**:
- task 작성 시 *list of known X* hardcode 박는 패턴 회피.
- 대신 *구조 신호* (list host ≠ article host + body 0자 + content-type audio/* 등) 명시.
- known list 는 *bootstrap* 보조용으로만 (4~6 host).

### β5. 청크 A 가 signal 노출 까지만, *enforcement 누락*

**잘못**: prompt 룰 (A-layer) 박았는데 LLM weight 약함. oxide attempt 3 = RSS 시도 후 article_body_len fail → retry feedback "body_empty_acceptable:true 박아라" 명시했지만 4회 retry 가능했어도 LLM 따른다는 보장 X. *F-layer enforcement* (register.py 가 LLM 무시하고 자동 override) 누락.

**올바른 흐름**:
- signal *노출* (A-layer prompt) + *enforcement* (F-layer post-LLM override) 둘 다 박아야 일반화 완성.
- 청크 A task 에 F-layer enforcement 명시 추가했어야.

### β6. case outcome SKILL 룰 위반

**잘못**: codex 가 4 case 다 `outcome: improved` 박았는데 SKILL.md §6.5 *re-probe 회복 함정* 룰 명시: AUTO 재생성 자동 통과해야 improved. 4 slug 다 N100 register fail = improved 아님. case_log log 호출 시 outcome=no_change 로 정정했지만 *case .md frontmatter* 와 DB row 불일치.

**올바른 흐름**:
- case_log log 호출 *전에* case .md frontmatter outcome 정정 + INDEX regen.
- codex 가 outcome 박는 단계에서 *re-probe 회복 함정* 룰 따르도록 task 에 명시.

### β7. cap_blocked 자동 분류 누락 (bot 분류기)

**잘못**: bloomberg /podcasts 가 403 Forbidden 인데 *rc=1 gen_fail* 로 분류 (register.py 가 4xx 보고 cap_blocked rc=5 으로 안 보냄). 내가 manual 으로 triage_later 박았음 — 자동 분류 게이트 누락.

**올바른 흐름**:
- register.py 또는 `bot/fail_taxonomy.py` 의 cap_blocked 룰에 `HTTPStatusError 403` 자동 분류 추가.

## 3. 파이프라인 개선 후보 (durable layer 박기)

각 후보 = *재발 방지* 게이트. **β 와 1:1 대응**.

| # | 개선 | 자리 | β |
|---|---|---|---|
| P1 | LLM 자동 회복 X 시 §2e 진입 강제 (no_change 단독 종료 금지) | `SKILL.md §0c-회피 게이트` 추가 | β1 |
| P2 | feed_candidates 의 *내용 검증* (item 수 / XML root tag) — 빈 feed 자동 reject + gate-fail park 후보 | `probe/extract.py` 의 feed_candidates 검증 + `register.py` 의 gate 추가 | β2 |
| P3 | SKILL.md §0b-2 P3 (empty/fake feed) 카테고리 추가 | `SKILL.md §0b-2` | β2 |
| P4 | task 작성 가이드: *list hardcode 박지 X, 구조 신호 의무* | `SKILL.md §0c` 또는 `codex_handoff.py` HARD_STOP 회피 게이트 5번 | β4 |
| P5 | 청크 task 의 *F-layer enforcement* 의무 명시 (A-layer prompt 만 박지 X) | `SKILL.md §0c` task 작성 룰 | β5 |
| P6 | `audio_share_host_detected` 구조 신호 재작성 (host list 제거 또는 bootstrap 강등) | `probe/extract.py` — **청크 C 가 박는 중** | β5 |
| P7 | F-layer register.py enforcement (structural 신호 시 article.body_empty_acceptable 강제 주입) | `scripts/register.py` — **청크 C 가 박는 중** | β5 |
| P8 | case_log log 호출 시 *case .md frontmatter outcome* 와 *DB row* 자동 정합성 체크 + 경고 | `scripts/case_log.py` | β6 |
| P9 | register.py 의 4xx (특히 403) → cap_blocked rc=5 자동 분류 | `scripts/register.py` 또는 `bot/fail_taxonomy.py` | β7 |
| P10 | hand-config 절차 명시: "자동 회복 X = §2e 진입 의무, no_change 단독 종료 금지" | `SKILL.md §1 또는 §5` | β1 |

## 4. 이번 세션 *외부* 효과 (영구 layer 박힘)

이번 세션에서 박은 *영구 게이트* (재발 차단 가치):

| layer | 영역 | 효과 |
|---|---|---|
| C (probe heuristic) | `probe/extract.py` rss_feed_urls + audio_share_host_detected (host list 기반) | RSS feed URL 추측 차단 — 미래 podcast 사이트 자동 풀 가능성 ↑. 단 host list hardcode = O(N) 확장 비용. |
| A (prompt) | `prompts/config_writer.system.txt` 3 룰 추가 (RSS URL · post_id link tail · audio share body skip) | LLM weight 약하지만 signal 노출. |
| C (probe heuristic — *청크 C 진행 중*) | structural 신호 (list host ≠ article host + body 0자 + content-type audio/*) | host list 무관 — 새 platform 자동 cover. |
| F (register enforcement — *청크 C 진행 중*) | structural 신호 시 article.body_empty_acceptable 강제 | LLM weight 무관 — 100% 적용. |
| F (radiolab handcrafted) | `configs/host_radiolab-org_podcast_0080db5b.json` | Nuxt skeleton wait — handcrafted, 다른 site 영향 X. |
| F (thisamericanlife / oxide handcrafted) | `configs/host_feeds-thisameri_talpodcast_c725ed7a.json` + `configs/host_oxide-computer_podcast_9f69bff0.json` | RSS handcrafted (link path tail / 진짜 feed host mapping). |
| gate-fail park (2 slug) | `triage_gate_failed.json` 16→17건 | cbs 빈 feed / dotnetrocks Blazor SPA. 분류기/게이트 보강 후 sweep-gate-fail 일괄 재판정 가능. |

→ 청크 C + 파이프라인 개선 (P1~P10) 박으면 다음 podcast batch 자동화율 ↑.

## 5. 다음 podcast 사이트 자동 시뮬레이션

청크 A+C 박힌 후 가상 새 podcast site (`example-podcast.com/feed` → Spreaker hosted) 들어왔을 때:

1. probe `feed_candidates` = `well-known-path` + RSS XML 200 OK + item 수 검증 → 진짜 게시판.
2. probe `rss_feed_urls` 휴리스틱 = link rel + HAR XML → spreaker.com host 추출.
3. probe `audio_share_host_detected` *structural* 신호 = list host (example-podcast.com) ≠ article host (api.spreaker.com) + body 0자 (또는 content-type audio/*) → detected=true confidence=structural.
4. LLM config 생성 (prompt 룰 = "rss_feed_urls[0].url 박아라"). RSS row 정상.
5. F-layer enforcement = register.py 가 article.body_empty_acceptable:true 강제 주입. body fetch fail 사전 차단.
6. validate + smoke + register baseline ✅.

→ 새 host list 추가 X. **자동 회복**.

## 6. retro 검증 절차

이 retro 문서 자체도 검증:
1. codex 리뷰 받기 (이 문서 + 청크 C diff).
2. P1~P10 중 청크 C 가 박는 것 (P6+P7) 외 나머지는 *별도 청크 D* 로 codex 위임.
3. P10 (SKILL.md hand-config 절차) 박힌 후 *다음 batch* 에서 자동 검증.

---

## 7. 청크 F1+F2+G — register 파이프라인 개선 (옵션 A site_kind enum)

세션 후반 사용자 goal = *batch 자동생성 실패 사이트 풀어내거나 게이트 거부*. 옵션 A (site_kind enum) 박는 3-청크 시퀀스 진행.

### 7a. 청크 F1 — critical fix (R-D1/R-D4/R-C1 봉합)

청크 C+D 의 Claude 직접 코드 리뷰 결과 3 critical risk 봉합:
- **R-D1**: `probe/discover.py:_verified_feed_candidate` fake `validated:True` fallback 제거. validate fail 시 `None`.
- **R-D4**: `scripts/register.py:_count_board_feed_signals` backward compat 룰 제거. validated=True 만 카운트.
- **R-C1**: `_generate` 의 모듈 글로벌 monkeypatch 제거 → `generate/generator.py:generate_config_validated` 에 `cfg_post_processor` callback 인자 추가.

commit `9ea7148`.

### 7b. 청크 F2 — site_kind 옵션 A 최소 viable

- `engine/digest.py:classify_site_kind` 신설 — 6 enum (`rss`/`podcast`/`static_html`/`spa_rendered`/`hybrid`/`unknown`) + confidence (high/med/low) + evidence + primary_feed_url.
- `scripts/register.py:_enforce_site_kind_config` 신설 — `kind=podcast/rss` high 시 list.url_template override (validated primary 만).
- `prompts/config_writer.system.txt` 에 site_kind 별 prompt hint 추가.
- `tests/probe_heuristics/test_site_kind.py` 신규 — 9 fixture (cbs/dotnetrocks/thisamericanlife/oxide/radiolab + static_html/hybrid/weak/host_known).

commit `04817bf` → main merge `f487b54`.

### 7c. Claude 직접 fix 2건 (F2 후 발견)

8 slug 테스트 도중 발견:

- **junk row filter** (commit `af41a2e`): `_html_same_host_row_count` 가 `head > meta` / `head > link` 같은 non-content row 도 카운트 — dotnetrocks Blazor SPA 의 28 junk row 가 `static_html high` 잘못 박힌 문제. selector root in (head/nav/footer/header/aside) 제외 + sample_url=None 제외.
- **backfill 순서 fix** (commit `8610d9c`): `register._build_digest` 의 `rss_feed_urls` 박는 순서가 *input-url-feed-path* (HTML SPA 추측) 우선 → 진짜 link rel feed URL 이 [1] 박혔던 버그. oxide 의 `primary_feed_url` 이 잘못된 URL 박힌 직접 원인. 순서: link rel + HAR XML → validated feed_candidates → fallback (input-url-feed-path 제외).
- **link_rel med confidence** (commit `e638bfe`): site_kind 분류가 옛 probe artifact (validated 키 없음) 의 link rel feed 도 source 로 사용. F enforcement 는 high 만 작동 — med 는 prompt hint 만. 안전.

### 7d. 8 slug N100 자동생성 테스트 결과

| slug | site_kind | register 결과 | 효과 |
|---|---|---|---|
| cbs.co.kr/podcast/ | (404 TARGET_NOT_FOUND) | ❌ 자동 거부 ✅ | 자동 거부 |
| dotnetrocks.com/RSS | rss med (link_rel: dotnetrocks.com/feed) | ❌ gen_fail | link_rel 가짜 RSS (Blazor SPA) — F enforcement med 안 작동, prompt hint 만 → LLM 이 가짜 URL 박음 |
| feeds.thisamericanlife.org/talpodcast | rss med (link_rel HAR XML) | ❌ gen_fail post_id_unique | LLM weight 부족 — post_id link path tail 룰 prompt 박혀있어도 LLM 이 follow X |
| **oxide.computer/podcast/rss.xml** | **hybrid med** (link_rel: feeds.transistor.fm) | ✅ **자동생성 30건** (시도 2 PASS) | **site_kind 핵심 효과 입증** |
| radiolab.org/podcast | spa_rendered high | ❌ gen_fail posts_nonempty | Nuxt skeleton selector LLM weight 부족 — handcrafted (.radiolab-card .card-title-link .h2) 박은 이유 그대로 |

= **1/5 자동생성 효과 입증** (oxide). 옵션 A 가 *handcrafted overhead 제거 가능성* 증명. dotnetrocks/thisamericanlife/radiolab fail = LLM weight 부족 또는 link_rel 검증 한계 (후속 청크 영역).

### 7e. 청크 G — 코드 리뷰 결과 후속 fix

청크 F (F1+F2+직접 fix) 박힌 후 codex read-only 리뷰가 9 issue 식별. 청크 G 가 critical 4 + minor 2 봉합:

- **A (medium)**: `primary_feed_url` 가 *unvalidated* link rel 도 박혀 prompt "validated" 주장과 불일치 → `_validated_or_linked_feeds` 분리 + link_rel 신호도 validated 표시 박힌 경우만 promote.
- **A2 (minor)**: JS signal 토큰 `"js"`/`"next"`/`"s4"` 단독 false positive → `"next.js"`/`"__next_data__"`/`"nextjs"`/`"render delta"` 로 정밀화.
- **C (medium)**: `_build_digest` backfill 순서 — link_rel 이 validated 앞 → validated 우선으로 정정.
- **D (medium)**: `ET.fromstring(text)` size cap 없음 + `_verified_feed_candidate` double fetch → `ET.iterparse(io.StringIO(text))` + `_MAX_FEED_VALIDATE_CHARS = 1_000_000` (1MB cap) + double fetch 제거.
- **E (minor)**: `_has_verified_feed` 와 `_count_board_feed_signals` legacy 처리 불일치 → `_has_verified_feed` 도 legacy 제거 (validated=True 만).
- **H (minor)**: case_log frontmatter hand-parse → `yaml.safe_load` 표준 parse.

commit `cd3749b` → main merge.

### 7f. 후속 청크 후보 (미진행)

리뷰가 식별한 jewel:

- **link_rel validate** — `rss_feed_urls` 의 link_rel feed 가 *진짜 RSS XML 인지* fetch + validate 박기. dotnetrocks `/feed` (Blazor SPA) 같은 가짜 feed 자동 거부. 1 fetch 비용 — 가치 큼.
- **LLM weight 강화** — thisamericanlife post_id_unique / radiolab Nuxt selector 같은 LLM 약점. retry feedback 의 dynamic injection (특정 fail pattern 보면 자동 inject) 또는 더 강한 모델로 escalation.
- **시간 budget** — `discover_feeds` 의 fetch 누적 10s+ 시간 — per-host concurrency limit (async) 또는 max_candidates cap.

다음 batch 진행 시 *site_kind=hybrid/podcast med* slug 가 자동생성 vs handcrafted 비율 측정.

### 7g. 최종 commit chain

| commit | 내용 |
|---|---|
| `32d036e` | merge chunk C — audio share structural + register enforcement |
| `219fb18` | merge chunk D — SKILL guards + feed validation + case_log warn + 4xx cap_blocked |
| `4cec12e` | retro 작성 (β1~β7 + P1~P10) |
| `f487b54` | merge F1 (R-D1/R-D4/R-C1) |
| `9ea7148` | (alt) F1 merge |
| `04817bf` | merge F2 (site_kind enum) |
| `af41a2e` | junk row filter |
| `e638bfe` | link_rel med confidence |
| `8610d9c` | backfill 순서 fix |
| `<TBD>` | merge G (review fixes A/A2/C/D/E/H) |

