---
slug: _batch_2026-05-24-games-official
date: 2026-05-27
outcome: improved
fix_layer: C+F
status: ✅ url_dead 게이트 5종 추가 — 16 registered / 48 url_dead / 33 gate_reject / 0 cap_blocked / 3 Later
failure_keys:
  - cross_host_redirect
  - parked_access_denied
  - js_redirect_to_lander
  - probe_timeout_host_dead
  - target_404_overrides_baseline
  - majority_not_found_with_empty_shell
tags: [batch, url_dead, gate, generalization, games-official]
---

# batch `2026-05-24-games-official` 처리

## 분포

| 단계 | registered | gen_fail (rc=1) | gate_reject (rc=3) | url_dead (rc=4) | cap_blocked (rc=5) |
|---|---|---|---|---|---|
| 초기 drain | 12 | 11 | 32 | 40 | 5 |
| retry1 (--failed all) | +4 | 3 (남음) | +1 (doom) | +4 | 0 (4 가 rc=4 로 reclassify) |
| retry2 | 0 | 3 | 0 | +4 (lethal/content) | 0 |
| **최종 (100)** | **16** | **0 active / 3 Later** | **33** | **48** | **0** |

사용자 의문: gate_reject + cap_blocked 결과를 보니 404 페이지가 많은데 왜 url_dead 안 가는지. 진단 결과 = **probe NOT_FOUND classification 정의에 cross-host redirect/parked-domain/probe-timeout-host-dead/baseline-blocked-overrides 가 빠져 있음** → 일반화 게이트 5종 추가로 봉합.

## 일반화 게이트 5종 (C+F-layer)

### 게이트 1: `CROSS_HOST_REDIRECT` (eTLD+1 비교)
- **신호**: input URL 의 final URL host eTLD+1 이 input 과 다름 (`slaythespire.com → megacrit.com`, `dontstarvegame.com → klei.com`, `fallout76.com → fallout.bethesda.net` 등)
- **자리**: `probe/diagnose.py:_cross_host_redirects` + `_registrable_domain`. 같은 baseline_ok 분기 안에서 "정적 HTTP로 충분" 보다 먼저.
- **F-layer**: `scripts/register.py:_policy_check` 가 verdict 에 `CROSS_HOST_REDIRECT` 있으면 거부. `is_url_dead` 조건에 포함 → rc=4.
- **false-positive 회피**: `_registrable_domain` 이 `www.example.com` 와 `example.com` 같음. locale path 추가 (`/en`) 는 host 비교라 무관.
- **회수**: 같은 batch rc=3 11+ slug + retry1 fallout76.com/news (rc=1 → rc=4) + 비-catalog 잠재 다수

### 게이트 2: `parked Access Denied` body marker (`signals.py`)
- **신호**: `<title>Access Denied</title>` body + visible text < 500 chars. Akamai EdgeAuth 류 parked domain (lethalcompany.com/lander, contentwarning.com/lander).
- **자리**: `probe/signals.py:_looks_like_parked_access_denied` → classify 안 NOT_FOUND.

### 게이트 3: `JS-redirect to parked path` body marker
- **신호**: `status==200` + `body < 400 bytes` + body 에 `window.location.href = "/lander|parked|expired"` 정규식. lethalcompany.com/contentwarning.com 의 JS-redirect shell.
- **자리**: `probe/signals.py:classify` NOT_FOUND 분기.

### 게이트 4: probe timeout + baseline HEAD 8s 무응답
- **신호**: `_run_probe` 가 `RegisterTimeoutError` 던지면 httpx HEAD 8s 로 base URL 시도. ConnectError/Timeout/RemoteProtocolError → host dead.
- **자리**: `scripts/register.py:_probe_timeout_host_dead_reason` + `_main_inner` 의 timeout 캐치 분기. dead 면 `_save_rejected` + rc=4.
- **회수**: hadesgame.com x2 (rc=1 → rc=4)

### 게이트 5: baseline 차단/오류 + target 명시적 NOT_FOUND
- **신호**: verdict 에 `CLOUDFLARE_PROTECTED_SITE`/`BASELINE_BLOCKED`/`WAF_406_BLOCK` + primary target results 가 모두 NOT_FOUND (또는 majority NOT_FOUND + 잔여 = "suspiciously empty body" BLOCKED_BOT)
- **자리**: `probe/diagnose.py` 의 verdict_parts loop 후 추가 분기.
- **majority 룰**: 4 strategy 중 3 NOT_FOUND + 1 empty-shell BLOCKED_BOT 의 lethalcompany 케이스 — `all()` 깨졌던 버그. OK 응답 0 + NF ≥2 + 잔여 = empty-shell 만 이면 TARGET_NOT_FOUND.
- **회수**: vampire-survivors.com/news (rc=5 → rc=4), lethalcompany/contentwarning x4 (rc=5 → rc=4), 사이트 통째 404 (옛 BASELINE_BLOCKED 가 rc=5 으로 새던 버그)

## 잔여 3 (Later 파킹)

### `host_factorio-com_blog_58038e74` — Atom feed extraction gap
- live: 200 + `<link rel="alternate" href="/blog/rss" type="application/atom+xml">` head 에 있음
- probe `feed_candidates: []` — head 의 `<link rel=alternate>` 못 추출
- 일반화 후보 (C-layer 후속): `probe/extract.py` 의 feed discovery 가 `<head>` head 의 `<link rel="alternate" type="application/...feed">` 도 emit
- bucket: Later (capability gap, agentic 입력 개선 또는 feed_extractor 보강 시 unpark)

### `host_slimerancher-co_news_6a5b691a` — SPA shell
- live: 200 + static HTML 에 `<h2>Subscribe!</h2>` `<h2>Join the Community!</h2>` (실제 news list 없음)
- probe `posts_nonempty 0건` — JS-render 안 함
- bucket: Later (render capability)

### `host_gearsofwar-com_root_84113a49` — React SPA
- live: 200 + `<title data-react-helmet="true">Gears of War | Home</title>` (no static content)
- probe `article URLs were relative; fetch_article got unknown url type` — agentic 가 SPA 에서 잘못된 selector 생성
- bucket: Later (render capability)

## Track A 진입 0 — 사용자 ship 요청 없음 (batch operator 흐름)

3 잔여 + 33 rc=3 (gate_reject) 모두 *명시 ship 요청 없는 batch operator 흐름*. ship evidence verbatim = 없음 (`Track A`/`수동 config`/`이 사이트 즉시 작동` 모두 미발견). Track A skip 정확.

## case_runs DB 영향

본 case 는 `_batch_*` (collective) 라 cases_index `--backfill-db` 후 한 row. fix_layer=C+F, outcome=improved (cross-site generic gate 추가). 후속 batch 들이 같은 패턴 자동 처리.
