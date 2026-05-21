# 거부 게이트 — 결정적 휴리스틱 → LLM index/content 분류기 veto

## Context

`scripts/register.py` 는 LLM config 생성 *전*, 5개 구조 휴리스틱 게이트로 "게시판(board) 아님" 을 판정해 `rc=3 gate_reject` 로 거부한다: `_single_article_nav_only_check` · `_meta_article_diverging_check` · `_multi_host_hub_check` · `_root_marketing_homepage_check` · `_board_shape_check`.

문제: 사이트 다양성 > 룰 추가 속도. 매 batch 마다 *진짜 게시판*을 "아님" 으로 거부하는 false-reject 발생 → 게이트마다 사이트별 escape 주석 누적(주먹구구). 근본 비대칭은 "게시판임의 *증거 부재*(`board_shape` 의 same-host 신호 합<1)" 로 거부하는 결정 구조 — probe 가 SPA/지연렌더를 못 잡으면 멀쩡한 게시판이 거부됨.

학계: index page(목록) vs content page(단일글) 분류는 LLM 으로 F1 0.89 / precision 0.98 (arXiv 2505.06972, title+body). 휴리스틱 baseline 천장은 F1 0.78. PoC 실측(gemini-2.5-flash, trafilatura 추출): board recall 0.905 / article precision 1.000, 잔여 miss 2건은 둘 다 SPA(현 게이트도 거부 = regression 0).

## Decision

5개 구조 게이트의 hard-reject 를 **LLM 분류기 veto** 로 감싼다. 게이트가 거부하려 할 때 `classify_index_content` 호출 → `index`(conf≥0.5) 면 **거부 취소**(일반 파이프라인 계속), `content`/실패 면 기존대로 거부.

- 입력 = `digest["list_html"]["source"]` raw HTML(trafilatura title+body) + `list_candidates` 구조 신호. cleaned `["html"]` 은 200KB cap 으로 SPA 본문 잘림 → source 우선.
- veto 는 `_save_rejected` *전* → override 시 마커·learned_blacklist 미발생.
- register 호출당 1회 memoize(digest 캐시) — 5게이트 + root_marketing 내부 board_shape 콜이 단일 verdict 공유(drift 불가, +1 LLM 콜만).
- `--gate-only` 는 veto skip(LLM 0콜 보장).
- 분류 실패/HTML 부재/trafilatura 미설치 → `class="?"` → 거부 유지 = **fail-safe**(status-quo, regression 0).

**veto 유지(거부 취소 안 함)**: `recognize_reject`(host 명시 known-article PATTERNS) + capability_blocked(rc=5 captcha) — 고정밀·false-reject 원인 아님.

### 대칭 확장 (2026-05-21) — accept-path content-reject

분류기는 `index`/`content` 대칭 출력인데 위 Decision 은 *거부 경로*(게이트 reject → index 면 구출)에만 썼다. 같은 분류기를 **수락 경로**에도 적용: 구조 게이트 *전부 통과* 후 `_accept_path_content_reject` 가 분류기 `content`(conf≥**0.7**) 면 거부(rc=3, `note="classifier: accept_path_content"`, learn=False). 게이트가 놓친 false-accept(비-게시판이 게이트 다 뚫고 등록 → 폴링 junk 영구/generation 헛돔)를 차단.

- 같은 register 호출의 memoized 분류 1콜 공유 — 게이트 reject 없이 통과한 등록은 여기서 첫 1콜(이전 0콜). 등록은 사이트당 1회라 비용 bounded(폴링 무관).
- **비대칭 임계**: 구출(override) conf≥0.5 / 거부(reject) conf≥0.7 — recall 우선 *유지*하되 *확신 있는* 비-게시판만 거부. article precision 1.000 → 진짜 게시판 오거부 ~0.
- `?`/저신뢰 → 수락 유지(fail-safe). `--gate-only` → skip. 알려진 플랫폼(discourse/xenforo recognize fast-path)은 board_shape 도달 전 early-return → 영향 없음.
- **철학 전환**: 원안의 "false-accept 허용(recall 우선)" tradeoff 를 *부분* 되돌림 — 사용자 결정(2026-05-21): "비-게시판 등록되어 triage/폴링 오염되는 게 더 큰 손해". 단 보수적 임계로 recall 손실 최소.

## Consequences

- **득**: false-reject 핵심(SPA·marketing-root·nav-only 오발화) 회복. wired 검증 6/6(보드 4 구출, article 2 거부유지). 게이트별 사이트 escape 주석 누적 압력↓.
- **실**: 결정적→확률적 거부. 게이트가 옳게 거부하던 비-게시판을 분류기가 "index" 로 통과시킬 수 있음(false-accept) → generation 헛돔. 사용자 "확실히 게시판 아닌 것만 거부" 선호 → 허용 tradeoff(graceful fail). would-be-reject 당 +1 gemini 콜. temperature=0 이나 LLM 비결정 가능 — 동일 URL 재등록 시 결과 흔들릴 여지(낮음).
- **미해결(별도 트랙)**: SPA 보드는 분류기도 정적 HTML 론 약함 — 진짜 해법은 render(playwright). classifier outage 시 영구 REJECTED 마커(learn=False 라 재등록 회수 가능) — fail-open 전환은 추후 판단.

설계·PoC 전말: `docs/plans/llm-index-content-classifier.md`. arXiv 2505.06972, trafilatura(Boilerpipe 계열) 차용은 `docs/webclaw 차용 검토.md §2-4` 결정의 연장.

---

## 확장 (2026-05-22) — multi-class page-type 분류기 (not_found / login 흡수, soft-404 regex 제거)

### 배경 (관측)

2026-05-22 FAILED-큐 batch 에서 드러난 한계: 분류기(이진 `index`/`content`)는 *5개 구조 게이트(rc=3)* 에만 wiring 됐는데, 거부의 다수는 그 경로 밖에서 났다.
- **apa-org** (`/science/about/psa/`): JS-렌더 후 "Page Not Found" not-found shell. probe verdict 는 `soft_404` 가 아니라 "JS 실행 필요" (nav 링크 17개를 row-like 로 셈) → 게이트/분류기는 *index 처럼* 통과 → config 생성 → fetch 0행 → `gen_fail(rc=1)`. 4회 retry 낭비.
- **soft_404 / login** 은 분류기 *이전* 단계의 결정적이지-않은 휴리스틱(`probe/extract.py:_SOFT_404_PATTERNS` regex, `probe/signals.py` 의 login 본문-마커/form)이 박는다 → 이진 분류기에 not_found/login 클래스가 없어 not-found shell 을 (링크 많다고) index 로 오판.
- **login over-fire**: `signals.py` 의 login 본문-마커(경로 2)·약마커+짧은본문(경로 3)·login form+짧은본문(경로 4) 은 *목록이 보이는데도* 사이드바 로그인 위젯만으로 LOGIN_REQUIRED 오판 가능 (length 가드로만 방어).

### Decision

분류기 출력을 이진 → **page-type 다중클래스 `{index, content, not_found, login}`** (+ `?`) 로 확장하고, 새 클래스를 **기존 rc 거부 어휘에 1:1 매핑** (새 어휘 0):

| class | 매핑 | 의미 |
|---|---|---|
| `index` | 수락 (+ soft-gate veto 시 거부 취소) | 게시판/목록 |
| `content` | `gate_reject` rc=3 | 단일 글 |
| `not_found` | `url_dead` rc=4 | not-found/error shell (soft-404 흡수) |
| `login` | `policy_reject` rc=2 | 로그인 게이트 (목록 안 보임) |

(`paywall` = teaser 보이면 content / 완전 게이트면 login 으로 접음. `error`(5xx) = transient → retry 영역, 분류 대상 X.)

**1. 비용 0 — 기존 memoized 콜 출력만 확장.** 게이트 단계 분류기는 register 호출당 이미 1회(memoized) 돈다(`_accept_path_content_reject` 가 게이트 reject 없어도 호출). 출력 클래스만 늘리면 not_found/login 을 *추가 LLM 콜 없이* 얻는다. `--gate-only` 는 여전히 LLM 0콜.

**2. 퍼지 본문-휴리스틱만 soft-gate(분류기 veto), 전송계층 결정적 신호는 hard.**

| 신호 | 성격 | 처리 |
|---|---|---|
| redirect → `/login` (`redirected_to_login`·final_url) | 서버가 튕김, 목록 미서빙 | **hard** policy_reject (분류기 안 봄) |
| HTTP 404 / `target_not_found` / `cert_or_dns_broken` | status 결정적 | **hard** url_dead |
| CF/Anubis JS-challenge raw 마커 등 | 인프라 고유 | hard (capability_blocked, 별 경로) |
| `signals.py` login 본문-마커/form (경로 2~4) | 200+본문, 목록 가릴 수도 안 가릴 수도 | **soft** — 분류기가 `index` 면 구출, `login` 이면 거부 |
| (구) `_SOFT_404_PATTERNS` 퍼지 본문 휴리스틱 | 200+not-found 텍스트 | **soft** — 분류기 `not_found` 가 판정 |

→ 분류기는 *퍼지 신호*를 양방향 교정: regex-miss(apa: verdict=JS필요인데 실은 not-found) 도 잡고, regex-false-positive(본문에 "not found"/login 위젯 있는 진짜 게시판) 도 `index` 로 구출.

**3. `_SOFT_404_PATTERNS` regex 제거.** 퍼지 soft-404 판정은 분류기 `not_found` 가 유일 arbiter (LLM > regex 정확도). LLM-독립 floor 는 *결정적 신호*(HTTP404/redirect/cert·dns)만 — 이건 LLM 없이도 동작.
- **근거(LLM-end-to-end)**: regex 를 "LLM 다운 fallback" 으로 유지하는 논리는 거의 무의미 — classify(gemini)가 다운이면 그 다음 `config_generate`(역시 gemini)도 다운이라 어차피 register 실패. regex 실익은 *LLM 은 살아있는데 classify 만 `?` 반환* 하는 좁은 경우뿐(temperature=0 구조화출력이라 드묾) → 그 경우 진행 → 진짜 not-found 면 config-gen 4회 후 `gen_fail`(드문 degrade, 옛 동작, 허용).

**4. 임계 (ADR 0007 비대칭 유지).** `index` 구출(override) conf≥0.5 / `content`·`not_found`·`login` 거부 conf≥0.7. not_found/login false-reject(진짜 게시판을 not-found·login 으로 오거부) = content false-reject 만큼 비싼 손실 → 보수적 0.7. `?`/저신뢰 → fail-safe(수락/진행).

### 구현 노트 (별 PR)

- `generate/classify.py`: 출력 파싱 `("index","content")` → `("index","content","not_found","login")`. 프롬프트(`prompts/classify.system.txt`)에 4-class 정의 + 경계(목록 보이면 login 마커 있어도 index; teaser paywall=content).
- `scripts/register.py`: verdict-reject 블록(현 ~1789)에서 *퍼지* 신호(soft_404, login 본문-마커/form)는 즉시 거부 X → `_classify_veto`(memoized) 호출해 분류기 출력으로 rc 결정. *결정적* 신호(redirect/HTTP404/cert)만 즉시 hard 거부. soft↔hard login 분리는 `signals.py` 의 `notable[]`(`"redirected to login"` vs `"login marker/form"`)로.
- `probe/extract.py`: `_SOFT_404_PATTERNS`·`detect_soft_404` 제거 (또는 호출부 분리). `probe/_contract.py` soft_404 필드·`probe/diagnose.py` verdict 분기 정리.

### Consequences

- **득**: soft-404·login 오판(false-reject 양방향) 을 LLM 판정으로 교정 — apa 류 gen_fail 4회 retry 낭비 차단(게이트 단계 rc=4 조기 거부), login over-fire(목록 보이는데 위젯만으로 거부) 해소. regex 휴리스틱(`_SOFT_404_PATTERNS`) 1개 제거 = rot↓. 새 어휘 0(기존 rc 매핑).
- **실**: not_found/login 판정이 결정적→확률적. 분류기가 not-found shell 을 `index` 로 흘리면 gen_fail 로 (옛 동작) degrade. `?` 비결정 여지(낮음). SPA not-found/login shell 은 정적 HTML 입력이라 여전히 약함(render 트랙 미해결, 위 본문과 동일 한계).
- **미해결**: 위 SPA 한계 동일. paywall 경계(teaser 분량)는 프롬프트 튜닝 영역.

설계 잠금: 2026-05-22 grill-with-docs 세션.
