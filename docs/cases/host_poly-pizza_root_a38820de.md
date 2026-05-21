---
slug: host_poly-pizza_root_a38820de
url: https://poly.pizza/
status: "🔧 손 config (playwright_html) + (E) schema: body_empty_acceptable + content=[] 허용"
outcome: improved
date: 2026-05-16
requested_by: poi23619
failure_keys: [schema_empty_fallback_chain, body_empty_acceptable_content_mismatch]
fix_layer: E
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: [engine/config_schema.py]
tags: [poly.pizza, mui, spa, 3d-model-catalog, body-empty-acceptable, schema-flag, prompt-schema-mismatch]
---

## 무엇이 일어났나
사용자 `/preview https://poly.pizza/` → 자동 등록 3회 FAIL — `config 검증 실패: article.content: 비어있는 fallback chain`.

last_config 는 `article: {fetch_kind: "html", body_empty_acceptable: true, content: []}`. 의도: 본문 없는 카탈로그 (3D 모델) — flag 박고 content selector 시도 안 함. **그런데 schema 의 `_check_fields({"content": []})` 가 빈 list 를 `비어있는 fallback chain` 으로 거부.** prompt (`prompts/config_writer.retry_skeleton.txt:19`) 는 명시적으로 "content 키는 비워두거나 가장 그럴듯한 후보 한두 개만 두면 됨" 이라 가르치는데 schema 는 거부 — **prompt 와 schema 모순**.

LLM 이 retry 3회 모두 "content=[]" 박았다가 schema fail → triage 큐. 의도대로 통과시키려면 dummy selector 하나라도 박았어야 하는데 prompt 가 그러지 말라 함.

## 픽스 (fix_layer: E)

### schema 룰 완화 — `engine/config_schema.py:272`
```python
if "content" in art:
    content_val = art["content"]
    body_optional = bool(art.get("body_empty_acceptable"))
    if not (body_optional and isinstance(content_val, list) and not content_val):
        _check_fields({"content": content_val}, "article", errs)
```
즉 `body_empty_acceptable: True` AND `content == []` 면 _check_fields 스킵. prompt 의 명시적 의도 ("content 비워두거나") 와 일치.

`body_empty_acceptable` 없이 `content: []` 는 여전히 거부 (기존 동작 유지) — 실수로 빈 content 박는 패턴 방어.

### 수동 config: `configs/host_poly-pizza_root_a38820de.json`
- strategy: playwright_html — 정적 fetch 는 MUI skeleton (`<MuiSkeleton...>` placeholder) 만 받음 (raw HTML 80kb 중 `/m/` 링크 0개). headless 만 33개 `/m/<id>` 링크 (probe list.html 153kb).
- wait_selector: `#featuredModels a[href^="/m/"]` — 카드 직접 대기
- row_selector: `#featuredModels > div.MuiGrid-item`
- post_id: `a[href^="/m/"]` href → `regex_extract ^/m/(.+)$`
- title: `.MuiCardHeader-title a` text
- author: `.MuiCardHeader-subheader a` text
- article: `body_empty_acceptable: true, content: []` — 픽스 후 schema 통과. 3D 모델 카탈로그는 "본문" 부재.

스모크: list 10건 OK (Sussy Imposter / Scifi Smg / Animated Character Base / ...).

## 트랙 B (일반화)
- **2a (인식기) — X.** poly.pizza 단일 카탈로그.
- **2b (--article-url) — X.** first_article_url=`/u/neptunecentury` (thankYouWall 패트론 — 본 카드 아님). 그래도 article-url 교정으론 본질 (schema 모순) 못 풀음.
- **2c (probe heuristic) — X.** probe 정상.
- **2d (probe artifact 수정) — X.**
- **(E) schema — O (이번 PR).** body_empty_acceptable + content=[] 모순 해소. piku 케이스 (커밋 e18e807) 가 신설한 플래그를 schema 가 안 따라간 후속 gap.

### 효과
| 단계 | 본문 없는 사이트 LLM auto-flow |
|---|---|
| 이번 PR 전 | LLM 이 `body_empty_acceptable=true, content=[]` 박음 → schema fail → 3회 retry 모두 같은 패턴 → triage |
| 이번 PR 후 | 같은 config 가 schema 통과 → register validate 의 article_body_len 도 `hard=False` (body_empty_acceptable=true) → 등록 OK |

## 자가 점검 (§6)
1. **자리**: E (schema). prompt 가 인가한 패턴을 schema 가 거부 → schema 의 누락. body_empty_acceptable 도입 (piku, 커밋 e18e807) 시 schema 룰 같이 못 박은 후속 fix.
2. **이전 케이스**: `host_piku-co-kr_w_4d61ac2c` (body_empty_acceptable flag 신설). 본 PR 이 그 flag 의 schema-side 일관성 완결.
3. **누구 깰까**: 0. `body_empty_acceptable` 없는 config 는 동작 불변. flag 박은 config 만 content=[] 허용 (opt-in 패턴).
4. **검증**:
   - `validate_config(...content:[]..., body_empty_acceptable:true)` PASS ✓
   - `validate_config(...content:[]..., flag 없음)` FAIL ("비어있는 fallback chain") ✓ (기존 동작)
   - probe_smoke PASS 272/0/4/0
   - 손-실행 list=10 OK
5. **outcome=improved, fix_layer=E, commit prefix `[fix-layer: E]`**.
6. **fixture**: 별도 schema test 미작성 — piku 케이스의 `tests/validate/test_body_empty_acceptable.py` 가 이미 flag 시맨틱 cover. 본 PR 은 *schema 룰만* 완화라 별 fixture 가치 boundary. 회귀 시점은 probe_smoke stage 3 (32/32 configs validate) 가 catch.
7. **트랙 B 매칭**: E (schema 완화) 1건. body_empty_acceptable 시맨틱의 *마지막* gap 해소.
