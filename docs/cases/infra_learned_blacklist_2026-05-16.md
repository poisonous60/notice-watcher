---
slug: infra_learned_blacklist_2026-05-16
url: (인프라 case — 특정 사이트 X. 트리거 = host_google-com_search_9440e9f9 의 후속 후속)
status: 🏗 인프라 (거부 패턴 자동 학습 시스템 — 한 사용자 거부 → 모두에게 적용, 등록 성공 = 자동 회수)
outcome: improved
date: 2026-05-16
fix_layer: F
failure_keys: [learned_blacklist, host_path_pattern, auto_learn, auto_unlearn]
config_strategy:
adapters_changed:
engine_files_touched: [bot/url_gate.py, bot/url_blacklist.json, bot/worker.py, bot/admin.py, scripts/register.py, tests/probe_heuristics/test_learned_blacklist.py]
tags: [self-improvement, policy-gate, learned-pattern, automation, dev-n100-sync]
requested_by: 운영자 (dev box session)
---

## 트리거

직전 case (host_google-com_search_9440e9f9 의 "## 후속 — board_shape_check anti-bot 구멍 보강") 처리 후 사용자 운영 시나리오 점검:

```
검색어만 바꿔서 다시 시도 (https://www.google.com/search?q=초카구야공주)
  → slug REJECTED 마커는 URL hash 단위라 안 잡힘 (다른 slug)
  → 사용자 의도: "한 사용자가 시도해서 거부된 URL 패턴은 다음 사용자도 거부되는 게 자연스러움"
```

즉 거부 *학습* 시스템 부재. 두 기존 시스템:
- **slug REJECTED 마커** (`output/poll_state/<slug>.REJECTED.json`) — URL hash 단위, 일회성.
- **url_blacklist** (`bot/url_blacklist.json`, `bot/url_gate.py:_check_policy`) — 운영자 손-편집 영구 룰 (host_suffix/path_ext).

둘이 데이터 안 공유. 자동 학습 없음. 한 명 거부됐다고 그게 *모두* 에게 자동 적용 안 됨.

## 픽스 (fix_layer: F — 5 파일 + 1 새 test)

### F-1. `bot/url_gate.py` — schema 확장 + 두 자리 merge

- `path_prefix` 필드 추가 (기존 host_suffix/path_ext 와 별개, 그룹당 셋 중 하나 이상).
- `_path_matches_prefix(path, prefixes)` — path 가 prefix 로 시작하면 True. 정규화: prefix 항상 `/` 로 시작 (사용자가 `search` 적어도 `/search`).
- `_check_policy` 가 그룹 안의 host_suffix + path_prefix 동시 있으면 **AND 매치** (둘 다 매치해야 hit). 한쪽만 있으면 그 쪽만.
- `_LEARNED_PATH = ROOT / "output" / "learned_blacklist.json"` 추가.
- `_load_blacklist` 가 *두 자리* read: `bot/url_blacklist.json` (운영자 룰, 위) + `output/learned_blacklist.json` (자동 학습, 아래). cache key = `(cfg_mtime, learned_mtime)` — 어느 한쪽 mtime 바뀌면 자동 reload. → **큐 처리 중 앞 작업이 거부하며 추가한 패턴이 뒤 작업에 즉시 반영**.
- `_learned_to_groups(patterns)` — learned 의 patterns dict 를 group 형식으로 변환 (각 pattern → 자기 message 가진 개별 group).

### F-2. `scripts/register.py` — 학습/회수 helper

- `_extract_url_pattern(url) -> (host, path_first_segment)` — host=소문자, path 첫 segment 만 (보수적). path=`/` 또는 빈 문자열이면 path_prefix=`""`. 예: `https://www.google.com/search?q=대나무` → `('www.google.com', '/search')`.
- `_pattern_id(host, path)` — sha1(host+'|'+path)[:12]. 결정성 (같은 입력 = 같은 id).
- `_read_learned()` / `_write_learned_atomic(data)` — tempfile + os.replace atomic write (partial-write reader 깨짐 방지).
- `_learn_pattern(url, reason, slug)` — 새 entry append 또는 기존 entry count 증가 + last_* 갱신.
- `_unlearn_pattern_if_match(url)` — 같은 (host, path_prefix) 매칭하는 entry 제거.
- `_list_learned()` / `_clear_learned_by_id(pat_id)` — admin 명령용.

### F-3. 통합 hook

- `_save_rejected(slug, url, reason, note)` 마지막에 `_learn_pattern(url, reason, slug)` 호출. 모든 REJECTED 마커가 자동으로 패턴도 박음. 실패하면 swallow (REJECTED 자체는 이미 박힘).
- `_save_state(slug, url, ...)` 마지막에 `_unlearn_pattern_if_match(url)` 호출. **등록 성공 = 그 host+path_prefix 패턴은 작동한다는 증거 → 자동 회수**. 실패하면 swallow (등록 자체는 성공).
- `bot/worker.py` rc=3 분기에서 `_save_rejected` 호출 추가 — 이전엔 triage 큐 안 쌓는다만 했지 REJECTED 마커도 안 박았음. 이제 자동 학습 hook 까지 흘러감. 사용자 메시지에 "같은 host/path 패턴은 이후 자동으로 거부됩니다" 추가.

### F-4. admin 명령

- `/admin learned` — list patterns (id, host_suffix, path_prefix, count, last_url). DM 으로 발송.
- `/admin unlearn <pattern_id>` — entry 제거 (false positive 복구). pattern_id regex `[a-f0-9]{1,12}`.

### F-5. `bot/url_blacklist.json` _comment 갱신 — path_prefix 필드 + learned_blacklist.json 자리 안내.

### F-6. `tests/probe_heuristics/test_learned_blacklist.py` — 33 케이스

- URL 패턴 추출 (정상/edge case)
- pattern_id 결정성
- 학습 (새 entry / 같은 패턴 count 증가 / 다른 path 별 entry)
- atomic write JSON 검증
- 회수 (정확 매치만 제거, 다른 path 보존)
- url_gate path_prefix 정규화 + AND 매치
- 통합: 학습 후 url_gate mtime reload → 검색어 다른 URL 도 즉시 거부

monkey-patch 로 LEARNED_PATH 를 `tempfile.TemporaryDirectory` 로 redirect → 실제 output/learned_blacklist.json 안 건드림. finally 에서 restore.

## 사용자 시점 동작

### 시나리오 1: 같은 패턴 다른 검색어
```
사용자 A: /preview https://www.google.com/search?q=대나무
  → board_shape_check 거부 (anti-bot redirect)
  → .REJECTED.json + learned_blacklist 에 (www.google.com, /search) 박힘
  → 봇 응답: "이 URL 은 게시판 형식이 아닌 것 같아요... 같은 host/path 패턴은 이후 자동으로 거부됩니다"

사용자 B: /preview https://www.google.com/search?q=초카구야공주
  → url_gate stage 2 에서 learned_rejected 그룹 매치 → 즉시 거부 (probe 안 돔, ~0s)
  → 봇 응답: "이전 시도에서 거부된 패턴이에요 — 사유: board_shape_check 게이트 거부. 같은 패턴은 다른 사용자가 시도해도 거부됩니다 (운영자가 /admin unlearn b10b233a0c32 으로 풀기 전까지)"
```

### 시나리오 2: dev 박스에서 손-config 으로 작동시킴 (false positive 회수)
```
dev 박스: register.py --config "configs/somesite.json"  # 작동 확인
  → _save_state → _unlearn_pattern_if_match(url) → 매칭 패턴 자동 제거
  → "[register] learned_blacklist: 매칭 패턴 자동 회수 — id=['b10b233a0c32']"

이후 사용자 시도: /watch <같은 패턴 URL>
  → url_gate stage 2 에 패턴 없음 → 정상 probe → 등록 진행
```

### 시나리오 3: 큐 처리 중 실시간 반영
```
큐: [job#1=google.com/search?q=A, job#2=google.com/search?q=B]
job#1 처리 → 거부 → learned_blacklist 에 패턴 박힘 (파일 mtime 변경)
job#2 처리 시작 → url_gate.check → _load_blacklist mtime cache invalidation → 새 패턴 즉시 적용 → 거부
```

mtime cache 가 핵심 — 봇 재시작 불필요. atomic write 가 partial-read race 방지.

## 영향

- **사용자 체감**: 검색어만 바꾼 같은 SERP URL 도 즉시 거부. probe 비용 (~10s) 절약. 거부 메시지가 "이전에 거부됨" 톤 ("운영자가 unlearn 으로 풀기 전까지").
- **운영자**: `/admin learned` 로 누적 거부 패턴 확인. false positive 발견 시 `/admin unlearn <id>` 로 즉시 회수.
- **자동 회수**: dev 박스에서 손-config 작성해 등록 성공 시 학습 패턴 자동 제거 — 사용자가 별 명령 안 해도 OK.
- **CLAUDE.md 룰 정합**:
  - `output/learned_blacklist.json` 은 `output/` 통째 .gitignore → git 추적 X (룰 B).
  - dev box / N100 두 자리 학습 *독립* — N100 운영 봇의 학습이 dev box 와 안 섞이는 게 의도된 동작. N100 학습은 N100 운영 패턴, dev box 학습은 dev 운영자 테스트 패턴.
  - 코드 변경 (`bot/`, `scripts/`) 은 git → dev box 만 작성 → N100 pull (룰 A).
- **회귀 risk**:
  - 정상 게시판 false positive: `_extract_url_pattern` 이 path 의 *첫 segment* 만 봐서 패턴이 보수적. 한 번 거부된 host 의 같은 첫 segment URL 만 잡힘. `scholar.google.com/scholar` 학습돼도 `scholar.google.com/citations` 안 잡힘.
  - 일시적 anti-bot rate limit → 영구 차단 risk: 있음. 운영자가 `/admin unlearn` 으로 손-회수 가능. memory 의 "가드레일 최소" 방침 일치.
  - cache invalidation race: mtime 검사가 stat 호출 — atomic write 의 os.replace 가 새 mtime 보장. cache 가 *직전* mtime 으로 hit 하는 윈도우는 ms 단위 — 큐 작업 사이 안전.

## 회귀 검증
- `python scripts/probe_smoke.py` → PASS 249 / FAIL 0 / WARN 4 (옛 diagnosis.json 무관). stage 5 의 새 23 파일 · 214 케이스 (이전 181 + 33 새) all green.
- `code-audit-reviewer` audit → 2 issues 발견 후 fix:
  - dead var `before = len(patterns)` (`scripts/register.py`) — 제거.
  - unreachable branch `path.startswith(pp + "?")` (`bot/url_gate.py`) — `urlsplit().path` 는 ? 안 포함 → 제거.
- 영향 configs 손-실행: 0건 — `register.py --config` 경로는 *기존* 학습 회수 hook 만 영향, 새 패턴 학습은 자동 등록 경로에서만.

## 트랙 B enumerate

이번 인프라 변경 자체가 트랙 B (미래 향 — 같은 패턴 자동 처리). 직전 case (host_google-com_search) 의 트랙 B 였던 `_board_shape_check` anti-bot 보강 위에 *더 일반화한* 학습 시스템 박음.

- 2a (인식기 확장) — X. 거부 학습은 인식기 책임 아님.
- 2b (--article-url) — X.
- 2c (probe 휴리스틱) — X. probe 신호 해석 변경 아님.
- **2d (probe artifact / register flow) — O.** `register.py` 의 `_save_rejected`/`_save_state` 가 학습/회수 hook 추가. 같은 PR.

## 관련

- 직전 case: `host_google-com_search_9440e9f9.md` ("## 후속 — board_shape_check anti-bot 구멍 보강 + REJECTED 마커")
- 자가개선 인프라: `docs/자가개선 인프라 계획.md` (rev 3)
- 두 시스템 (slug REJECTED, url_blacklist) 의 결합 — 이번 PR 이 brige 박음
