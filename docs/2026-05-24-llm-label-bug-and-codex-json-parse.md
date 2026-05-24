# 2026-05-24 — LLM 에러 라벨 stale + codex JSON parse 실패 다발

## TL;DR

1. **라벨 버그**: `generate/generator.py:161` 가 `LLMError` 를 `"gemini 호출/파싱 실패: ..."` 로 감쌌음. routing 이 codex/openrouter 로 바뀐 뒤에도 텍스트가 "gemini" 박혀 있음 → dashboard `/candidates` 에서 *codex 실패가 `gemini_api` subkind 로 라벨링됨*. 사용자가 "Gemini 키 문제 아니냐" 오인.
2. **분류기 버그**: `bot/fail_taxonomy.py` 의 `gemini_api` subkind 매처가 `"gemini 호출"` 토큰만 잡고 provider 식별 X. 위 stale 라벨과 짝지어 codex 실패를 통째로 흡수.
3. **진짜 실패**: codex (`gpt-5.4-mini`) 가 큰 config 응답에서 malformed JSON 을 뱉음 (예: govinfo job#1702 — `Expecting ',' delimiter: line 1 column 2556 (char 2555)`). API 호출 자체는 200 OK — usage 로그엔 `ok` 로 박힘. usage 로그의 `http_error` 38건은 전부 `notify_*` 단의 Gemini 503 (자동등록 무관).

## 픽스 (이 커밋)

### A. 에러 라벨 provider-aware + API/parse 분리

문제: `client.provider` 만 쓰면 `FallbackClient` wrap 시 항상 `"fallback"` 박힘 (codex review 캐치). 진짜 응답 *준* provider 가 codex 인데 라벨이 `(fallback)` — 정보 손실. 또 API 실패와 응답 본문 JSON 파싱 실패가 한 try 블록에 묶여 분류 어려움.

해결:

1. `LLMResponse` 에 `provider: str` 필드 추가 ([`generate/llm_base.py:43-55`](../generate/llm_base.py#L43)). 부모 `LLMClient.generate` 가 success path 에서 `resp.provider = self.provider` 박음 ([`generate/llm_base.py:99-103`](../generate/llm_base.py#L99)).
2. `FallbackClient.generate` 는 primary/fallback 의 `generate()` 반환값을 그대로 패스 — `resp.provider` 가 실제 응답 준 쪽 (`"codex"` 또는 `"gemini"`) 으로 박힘.
3. `generator.py:_generate_raw` ([`generate/generator.py:153-167`](../generate/generator.py#L153)) 를 2-try 로 분리:

```diff
- try:
-     resp = client.generate(...)
-     cfg = _parse_json_loose(resp.text)
- except LLMError as e:
-     raise GenerationError(f"gemini 호출/파싱 실패: {e}") from e
+ try:
+     resp = client.generate(...)
+ except LLMError as e:
+     raise GenerationError(f"LLM 호출 실패 ({client.provider}): {e}") from e
+ try:
+     cfg = _parse_json_loose(resp.text)
+ except LLMError as e:
+     raise GenerationError(f"LLM 응답 JSON 파싱 실패 ({resp.provider or client.provider}): {e}") from e
```

새 에러 메시지 예:
- **API 실패** (primary+fallback 둘 다 실패): `LLM 호출 실패 (fallback): codex network err; gemini 429 RESOURCE_EXHAUSTED` — `(fallback)` 라벨이 의미 있음("둘 다 실패").
- **API 실패** (직접 routing, fallback 없이): `LLM 호출 실패 (gemini): Gemini API 503: ...`.
- **응답 JSON 깨짐** (codex via FallbackClient): `LLM 응답 JSON 파싱 실패 (codex): 모델 응답을 JSON 으로 파싱 실패: Expecting ',' delimiter ...` — `resp.provider` 가 실제 codex 박음.
- **응답 JSON 깨짐** (gemini direct): `LLM 응답 JSON 파싱 실패 (gemini): ...`.

### B. subkind 분리: `gemini_api` → `llm_parse` + `llm_api`

[`bot/fail_taxonomy.py:199-217`](../bot/fail_taxonomy.py#L199):

- **`llm_parse`** — 응답 JSON 깨짐. 토큰: `JSON 으로 파싱 실패` / `Expecting ',' delimiter` / `Expecting value` / `Expecting property name`. **처방**: prompt schema 강화 / 다른 모델 라우팅. *API 는 성공*.
- **`llm_api`** — API 단 실패. 토큰: `RESOURCE_EXHAUSTED` / `UNAVAILABLE` / `LLM 호출` / `gemini 호출`(legacy alias). **처방**: 재시도 / 키 추가 / 공급자 변경.

순서: `llm_parse` *먼저* (더 구체적). parse 실패는 보통 두 토큰 다 박힘 ("LLM 호출/파싱 실패 ... JSON 으로 파싱 실패") — parse 가 이김.

backward-compat: 옛 DB row 의 `gemini 호출` 토큰도 `llm_api` 가 alias 로 잡음. dashboard 의 옛 카운트는 `llm_api` 에 합쳐짐. 옛 parse-fail row 는 자동으로 `llm_parse` 로 재분류 (read-time 파생, ADR 0002).

### C. 테스트 + 문서

- `tests/fail_taxonomy/test_classify_fail.py` — 새 fixture 5개 (llm_api new label / llm_api legacy gemini label / llm_api unavailable / llm_parse codex / llm_parse legacy gemini label) + 옛 `gen_fail_unknown_fail_beats_gemini_token` → `..._beats_llm_token` 으로 rename. completeness test 자동 통과 (각 fixed subkind 가 fixture 에 등장).
- `docs/fail 분류.md` — `scripts/gen_fail_taxonomy_doc.py` 로 자동 재생성.
- `docs/config 자동생성 실패 케이스.md` §2e — provider-agnostic 표현 + 두 subkind 분기 설명.
- `CONTEXT.md` — fail_subkind 어휘 갱신.
- `.claude/skills/hand-config/SKILL.md` §dynamic-subkind-priority — 새 ordering 설명.

## 별도 후속 — codex `gpt-5.4-mini` JSON 깨짐 (코드 픽스 아님)

진짜 사이트 등록을 막은 원인. 이 커밋은 *분류만* 고침. 실제 codex parse 실패 자체는 별도 픽스 후보:

### 데이터

`output/usage.sqlite3` 의 `config_generate` / `config_retry` codex 호출에서 raw JSON 응답 파싱이 자주 깨짐. 예: govinfo job#1702 (`host_govinfo-gov_root_2458d525`) — codex 가 char 2555 에서 `,` 누락. 사이트 selector 가 큰 응답 (≥2KB) 에서 빈번. usage 로그상 200 OK (`status='ok'`) 라 `http_error` 카운트엔 안 잡힘 → 모니터링 사각지대였음.

### 후보 픽스 (택일 또는 조합)

1. **routing 폴백**: `config_generate` / `config_retry` 가 `codex:gpt-5.4-mini` → `gemini:gemini-2.5-flash` 로 fallback. 이미 `FallbackClient` ([generate/routing.py:155](../generate/routing.py#L155)) 인프라 있음 — routing.json 값을 `codex:gpt-5.4-mini#low` 대신 별도 wrapper 로 바꿔야 함. 현재는 codex provider 1개만 라우팅 시 native wrapper 적용.
2. **모델 격상**: `gpt-5.4-mini` → `gpt-5.4` (full) 풀버전, 또는 `#low` → `#medium`/`#high` (reasoning effort). mini 가 큰 응답에서 JSON 깨먹는다는 가설. 비용 ~3x.
3. **prompt schema 강화**: [generate/prompts.py](../generate/prompts.py) 의 출력 schema 에 "JSON 외 텍스트 금지", escape 룰 명시. 효과 불확실 (모델 따라).
4. **JSON 복구 시도** *(2026-05-24 박음)*: [`generate/gemini.py:_parse_json_loose`](../generate/gemini.py) 에 `json_repair` pip 라이브러리 2차 fallback. `Expecting ',' delimiter` / trailing comma / 닫히지 않은 brace 등 1~몇 글자 누락은 자동 회수. 빈 dict / `""` 반환은 채택 X (garbage 가 schema validate 우회하지 않도록). 운영자 가시성 위해 복구 성공 시 `[json_repair]` print. 테스트: [`tests/llm/test_json_repair.py`](../tests/llm/test_json_repair.py) (9/9 pass — 정상 / fence / outer-brace-cut / missing comma / trailing comma / unclosed brace / garbage reject / empty dict pass / blank reject).

남은 순서: (4) 효과를 1-2 batch 측정 → 회수율 낮으면 (1) 또는 (2) 박기.

### 사용자 결정 필요

(1)~(3) 중 어느 것 추가로 박을지는 (4) 효과 측정 후. 일부 실패는 1글자 누락 이상의 깊은 깨짐이라 repair 도 못 살림 — 그 비율이 의미 있으면 routing/모델 손봐야.

## 메모: usage 로그의 `http_error` 38건은 자동등록 무관

- 전부 `notify_summarize`(20) / `notify_filter`(18) — Discord 알림 본문 요약/필터 단계.
- 24h 8건 전부 `notify_summarize` 503 Service Unavailable (Google 측 transient). caller 가 `[warn] LLM 요약 실패 ... 본문 발췌로 폴백` 으로 잡아서 raw 본문 발췌 보냄. 사용자 발송 X 끊김.
- `config_generate` / `config_retry` / `classify_index_content` 의 gemini `http_error` = **0건** (all-time).

→ dashboard `/llm-usage` 의 http_error 카운트가 자동등록 실패와 *상관없음*. 두 화면 (`/llm-usage` 와 `/candidates`) 동시에 본 사용자가 인과 오인하기 쉬움. 별도 후속으로 `/llm-usage` 에 call_site 필터 default = register-only 셋팅 고려 가능.

## 박힌 게이트 — 재발 차단

CLAUDE.md §8a (영구 게이트 우선) 적용:

1. **에러 wrapper provider-aware** ([generator.py:161](../generate/generator.py#L161)) — 새 provider 추가해도 자동으로 라벨 정확. 옛 `"gemini"` 하드코딩 stale 못 박힘.
2. **subkind 의미 분리** (`llm_parse` vs `llm_api`) — provider 와 무관하게 *증상* 으로 분류. routing 바뀌어도 의미 안 깨짐.
3. **테스트 fixture** — legacy "gemini" 라벨 + 새 "LLM ({provider})" 라벨 둘 다 분류 정확한지 회귀 차단.

다음에 LLM 라우팅 바꿔도 분류기는 안 깨짐.
