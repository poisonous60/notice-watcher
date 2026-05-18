# 2026-05-18 — vocab-ext design: `response_branch_body` (`from:"branch"` source kind)

vocab-ext SKILL 첫 dogfood. [docs/2026-05-18-prior-art-followup-plan.md](2026-05-18-prior-art-followup-plan.md) Action #3 의 *design only* 산출물. 구현 *전* reviewer 검증 받음.

ADR `docs/adr/0003-vocabulary-extension-skill.md` + SKILL `.claude/skills/vocabulary-extension/SKILL.md` 따름.

## 1. 후보 평가 (SKILL §2)

### 2a. 영향 사이트 수 (정직 평가)
트리거 3 cases — 평가 결과:

| case | 패턴 | 새 어휘로 표현? | config 전환 가능? |
|---|---|---|---|
| `cafe.naver.com_..._30291108_...` (NaverCafe) | 본문 API 401/403 → 본문 비움 | **불필요** — 기존 `article.skip_status: [401,403]` 으로 OK (codex MAJOR 2) | 별 작업 필요 (목록 multi-API merge 등 다른 vocab 도) |
| `m.cafe.daum.net_umamusume-kor_...` (DaumCafe) | 본문 401/403 → 비움 + 목록 = inline JS array | **불필요** — `skip_status` 로 OK. 목록은 다른 vocab (`inline_js_array_scrape`) | 목록 패턴이 더 핵심 |
| `www.reddit.com_r_CosmicPrincessKaguya` (Reddit) | 4 종 본문 합성 (self / 이미지 / 갤러리 / 링크) | **부분만** — self 분기 (`selftext_html`) 는 OK. 이미지/갤러리/링크 = HTML *합성* 필요 (closed vocab 표현 불가) | **handwritten 유지** — 합성 때문 |

→ **실제 config 전환 가능 사이트 = 0**. 단 새 어휘는:
- *미래* 비슷한 패턴 (응답 type field 보고 본문 path 분기) 사이트에 사용 가능 (예: type=ARTICLE → content path A, type=VIDEO → content path B)
- 일부 case 의 *부분* 표현 가능 (Reddit self 글만, 갤러리는 못함)

### 2b. engine 변경 범위
- `engine/extract_helpers.py` — `_resolve_source` 에 `from:"branch"` 분기 추가 (~20 line)
- `engine/config_schema.py` — `_SOURCE_KINDS` 에 "branch" 추가 + `_check_source` 에 branch 검증 룰 (~20 line)
- `prompts/config_writer.system.txt` — `from:"branch"` 어휘 한 줄 추가 (fix-layer A) + `## article 키` 의 content 설명 보강
- `generate/prompt.py` `_EXAMPLE_CONFIG_FILES` — 합성 example 1개 (fix-layer B)
- `tests/engine/test_branch_source.py` 신규 — fixture 3개

### 2c. 안전성
- **closed vocab 폭주**: 새 source kind 1개 추가 = 어휘 학습 부담 *약간 증가*. 단 자연 확장 (기존 source dict 형식 재사용 — when 조건만 신규)
- **backward compat**: ✅ 기존 chain 안에 새 source kind 추가 — 기존 14 config 미영향
- **LLM 어휘 학습**: prompt 어휘 1개 추가 — generate 단계에서 LLM 이 *적절한* 사용 판단 어려울 수 있음. few-shot example 필수

### 2d. ROI 합산
- 영향 사이트 (현재 0 + 미래 후보 1~2) / 비용 (반나절~1일 코드) — **낮음**
- ⚠️ codex 도 §3 미정 (a) "engine 어휘만 추가 + config 전환은 별 작업" 으로 ROI 제한 인지

### 2e. 결정 후보
1. **박기** — engine 어휘 + prompt + tests. 미래 사이트 대비. ROI 낮음 인정.
2. **보류** — 현재 영향 0건. 같은 후보 *4건+* 누적 시 재진입 (Reddit-like 합성 어휘는 별도).
3. **scope 재정의** — `response_branch_body` 후보를 *제거* 하고 새 후보 (`status_skip_reuse`, `synthesized_content`) 로 재분류.

**design 권장 = 옵션 3 (scope 재정의)**:
- 트리거 카운트는 *카테고리 오분류*. NaverCafe/DaumCafe = 기존 vocab (`skip_status`) 으로 OK → 후보에서 제거.
- Reddit 만 진짜 신규 패턴 → 새 후보 `synthesized_content` 로 재분류 (closed vocab 확장 어려움 — 별 작업).
- **새 어휘 박기 = 보류** (현 raw evidence 로는 ROI X).

단 codex 리뷰 + 사용자 결정 따름. 본 문서는 옵션 1·2 대비 옵션 3 권장만 명시.

---

## 2. (옵션 1 시) Branch source kind design

옵션 1 (박기) 선택 시 구체 design. 옵션 3 (재정의·보류) 시 생략.

### 2.1. Source dict shape

```json
{
  "from": "branch",
  "when": {
    "field_eq": {
      "path": ["data", "is_self"],
      "value": true
    }
  },
  "source": {
    "from": "json",
    "path": ["data", "selftext_html"]
  },
  "transform": [["collapse_ws"]]
}
```

- `when` (object, 필수) — 평가 조건. 현 단계 = `field_eq` 만 (확장 여지: `field_in`, `and`, `or`).
- `when.field_eq.path` (list, 필수) — JSON path (item 기준, `navigate_json` 사용).
- `when.field_eq.value` (any, 필수) — 정확 일치 (== 비교, type-strict).
- `source` (object, 필수) — 매칭 시 평가할 source. 기존 source 형식 그대로 (`{from:"json",path:[...]}` 등). 중첩 `from:"branch"` 도 허용 (decision tree).
- `transform` (선택) — branch source *자체* 의 transform chain. `source` 결과에 적용.

### 2.2. Semantics (evaluation)

`_resolve_source(root, item, source, context)` 안:

```python
elif kind == "branch":
    when = source.get("when") or {}
    field_eq = when.get("field_eq") or {}
    cur = navigate_json(item, field_eq.get("path"))
    if cur != field_eq.get("value"):
        return None        # 미매칭 → chain 다음으로
    raw = _resolve_source(root, item, source["source"], context)
```

- 미매칭 → `None` → `extract_field` chain 이 다음 item 시도 (자연스러운 fallback).
- 매칭 → 내부 source 평가. 내부도 None 이면 chain 다음.

### 2.3. Validation (config_schema.py)

```python
_SOURCE_KINDS = {..., "branch"}

# _check_source 안
elif kind == "branch":
    when = src.get("when")
    if not isinstance(when, dict):
        errs.append(f"{where}: branch source 는 'when' 객체 필요")
    else:
        feq = when.get("field_eq")
        if not isinstance(feq, dict):
            errs.append(f"{where}.when: 'field_eq' 객체 필요 (현 단계 유일 조건)")
        else:
            if not isinstance(feq.get("path"), list):
                errs.append(f"{where}.when.field_eq: 'path' 리스트 필요")
            if "value" not in feq:
                errs.append(f"{where}.when.field_eq: 'value' 키 필요 (null 도 OK)")
    inner = src.get("source")
    if not isinstance(inner, dict):
        errs.append(f"{where}: branch source 는 'source' (내부 source dict) 필요")
    else:
        _check_source(inner, f"{where}.source", errs, available_fields=avail)
```

### 2.4. Prompt 어휘 추가 (fix-layer A)

`prompts/config_writer.system.txt` 의 `## source dict ("from" 별)` 섹션 끝에 한 줄 추가:

```
- {from:"branch", when:{field_eq:{path:[...], value:<x>}}, source:<source dict>} : item(JSON) 의 path 값이 value 와 정확 일치하면 source 평가, 아니면 None (chain fallback). 응답 type/kind field 보고 본문 path 분기할 때(예: Reddit 의 is_self/post_hint). 합성 본문(HTML 문자열 생성) 은 closed vocab 표현 불가 — handwritten 어댑터로.
```

`## article 키` 의 content 설명에 추가:

```
- 응답 type/kind field 로 본문 path 가 다르면 (Reddit 의 is_self/is_gallery 등) [{from:"branch", when:..., source:...}, {from:"branch", ...}, {from:"const", value:"<fallback link>"}] chain 으로 표현.
```

### 2.5. Few-shot example (fix-layer B)

`generate/prompt.py` `_EXAMPLE_CONFIG_FILES` — Reddit subset 가공 (가공: 합성 분기 제외, self/non-self 단순 fallback 만):

```json
{
  "version": 1,
  "site": "example-forum.com",
  "board": "general",
  "strategy": "httpx_json",
  "list": { ... },
  "article": {
    "url_template": "https://example-forum.com/api/post/{post_id}.json",
    "fetch_kind": "json",
    "data_path": ["data"],
    "content": [
      {
        "from": "branch",
        "when": {"field_eq": {"path": ["type"], "value": "article"}},
        "source": {"from": "json", "path": ["body_html"]}
      },
      {
        "from": "branch",
        "when": {"field_eq": {"path": ["type"], "value": "link"}},
        "source": {"from": "template", "value": "<a href=\"{external_url}\">외부 링크</a>"}
      },
      {"from": "const", "value": "<p>본문 없음</p>"}
    ]
  }
}
```

### 2.6. Test fixtures

`tests/engine/test_branch_source.py`:

1. **matched** — `item = {"data": {"is_self": True, "selftext_html": "<p>hi</p>"}}` + branch when=is_self/True → "<p>hi</p>"
2. **not_matched, fallback** — `item = {"data": {"is_self": False}}` + chain `[branch, const "<a>link</a>"]` → "<a>link</a>"
3. **nested branch** — chain 안 branch 2개 + const fallback. 첫 매칭 X, 둘째 매칭 → 둘째 결과
4. **type mismatch** — `value: 1` vs item 의 `"1"` (str) → None (type-strict 확인)
5. **invalid schema** — `_check_source` 에 incomplete branch → ConfigError

---

## 3. Regression scope (ADR 0003 §smoke scope, codex MINOR 1 반영)

옵션 1 박기 시:

1. `python scripts/probe_smoke.py` 그린 (stage 3 + stage 5)
2. `configs/*.json` 37개 (current count) `validate_config()` 통과 — 새 `_SOURCE_KINDS` 가 옛 config 깨지지 X
3. **같은 strategy 전체** 회귀:
   - `handwritten` 5개 (Arca/DaumCafe/NaverCafe/Reddit/...) — adapter unchanged, kwargs unchanged → fetch_list 1건 sanity
   - `httpx_json` N개 — content chain 에 branch 안 박혔으면 영향 X. validate 통과 확인
   - `httpx_html` / `playwright_html` 동
4. Gemini 토큰 비용 telemetry (v2 신규):
   - prompt diff byte = +500~700 bytes 추정 (어휘 1개 + few-shot 1개)
   - 신규 prompt 첫 run token count 기록 (`scripts/probe_smoke.py` 의 generate 호출 시 stdout 캡처)
5. reviewer subagent (`hand-config-reviewer`) PASS:
   - rubric 9~12 이미 `.claude/agents/hand-config-reviewer.md` line 76~ 존재 — *추가 없음*
   - main thread 가 §3 결과 (1~4) 첨부 의무 (codex NIT 반영)

---

## 4. Rollback (옵션 1 fail 시)

- `git revert <commit>` — engine + schema + prompt + tests 한 commit 되돌림
- 영향 case .md (3개) 에 `vocab_attempt_failed: true` + `failure_reason` 박음 → 다음 호출 자동 강등
- `output/vocab_alerts.json` 정리 (선택 — history 보존 가능)
- `.bak` 복구 없음 (config 변경 X — engine 만)

---

## 5. 결론 (design 권장)

**옵션 3 (scope 재정의 + 보류) 권장**. 이유:

1. 트리거 3 cases 중 *진짜 새 어휘 필요* 한 케이스 = Reddit 1건. NaverCafe/DaumCafe 는 기존 `skip_status` 로 OK.
2. Reddit 의 진짜 어려움 = *본문 합성* (HTML 문자열 생성) — closed vocab 표현 *어려움 X* (불가). branch source 추가해도 self 분기만 가능, 갤러리/이미지 결국 handwritten 유지.
3. 현재 ROI = engine 어휘 추가 ↔ 실제 config 전환 0건. dogfood 가치 (mechanism 검증) 가 유일 이득.

**실행 권장**:
- (a) 본 design 문서 + reviewer subagent 검토 → 옵션 1/2/3 사용자 결정
- (b) 옵션 1 박기 결정 시: 본 §2 design 그대로 구현 + §3 regression + §4 rollback
- (c) 옵션 2/3 보류 결정 시: case .md frontmatter 정리:
  - NaverCafe/DaumCafe 의 `response_branch_body` 후보 → `not_applicable` (skip_status 로 OK 명시)
  - Reddit 의 후보 → 새 후보 `synthesized_content_html` 로 분류 (high, 단독 — 임계 미달)
  - vocab-trigger 재실행 → triggered = 비어있음. dashboard `/vocab-deferred` 반영

본 design 의 *반-결론* (어휘 안 박음 권장) 자체가 vocab-ext SKILL 의 valid output — SKILL.md §2e 의 "지금은 다 보류" 케이스. ADR 0003 dogfood 성공 (mechanism 작동 확인) + 첫 진입에서 *비박기* 결정 = 캐시 오염 방어 (codex 2c 안전성) 입증.

## 6. 결정 필요

사용자 + reviewer subagent 검토 후:
- 옵션 1 박기 → §2 design 구현 시작 (1.5일)
- 옵션 2 보류 → case .md 변경 없음. 다음 hand-config 진입 시 재카운트
- 옵션 3 재정의 → case .md 4건 정리 + 새 후보 도입 (0.5일)

design 권장 = 옵션 3.
