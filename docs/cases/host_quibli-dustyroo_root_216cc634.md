---
slug: host_quibli-dustyroo_root_216cc634
url: https://quibli.dustyroom.com/
status: "🔧 손 config (httpx_html) + (F+A) transforms: _strip(value, chars=None) + prompt 한 줄 — LLM 의 [\"strip\",\"/\"] 아릴리티 fix"
outcome: improved
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty_0, transform_strip_arity_error, silent_field_dropout]
fix_layer: F+A
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/transforms.py, prompts/config_writer.system.txt]
tags: [quibli, dustyroom, jekyll, docs-site, unity-shader, transform-strip-arity]
---

## 무엇이 일어났나
사용자 `/preview https://quibli.dustyroom.com/` → 자동 등록 3회 FAIL — `[FAIL] posts_nonempty: 0건`.

last_config row_selector `nav.nav__list ul.nav__items > li > ul > li > a` 는 정적 fetch 에서 19개 매칭 (BS4 select 검증). 그런데 adapter `fetch_list` 는 0건. 원인: post_id transform `["strip","/"]` 가 `_strip(value)` 의 1-arg 시그니처와 충돌 → `TypeError: _strip() takes 1 positional argument but 2 were given` → `extract_field` 가 `except Exception` 으로 잡고 None 반환 → post_id 비어서 row 드랍 (`_build_post` 가 None).

LLM 은 Python 의 `str.strip("/")` 관용구를 그대로 박았는데, transforms 의 `_strip` 은 인자 받지 X. **silent failure** — schema 통과, runtime 0건.

## 픽스

### (F) `engine/transforms.py:_strip(value, chars=None)` — chars 인자 받게
`value.strip(chars) if chars else value.strip()`. `_strip(value)` 와 `_strip(value, "/")` 양쪽 동작. LLM 관용구 자연.

`prompts/config_writer.system.txt` 의 transform 용법 목록에 `["strip"] / ["strip","/"]` 한 줄 추가 — 명시화.

### 수동 config
- strategy: httpx_html (probe 가 playwright_html 권고했지만 정적 fetch 가 nav 다 잡음 — 충분)
- row_selector: 위 그대로
- post_id transform: `[["remove_prefix","/"],["regex_extract","^([^/]+)"]]` (slash 떼고 첫 path segment) — 픽스 후엔 `["strip","/"]` 도 동등하나 명시적 chain 이 의도 명확
- title/url 정상
- article.content: `section.page__content` html

스모크: list 10건 OK, body 11028자.

## 트랙 B (일반화)
- **2a (인식기) — X.** Jekyll Minimal Mistakes 테마 SaaS 가 아니라 단일 docs 사이트.
- **2b (--article-url) — X.** first_article_url 가 anchor (`#gradient`) 이지만 list selector 본질과 무관.
- **2c (probe heuristic) — X.** probe artifact 는 정상 — 문제는 LLM 의 transform 오용.
- **(E) schema 거부 — O 가능 (별 PR).** transform arity 검증을 schema 에 추가 가능 (현재 name 만 검증, args 미검증). 단 모든 transform 의 시그니처 introspect 필요 → 본 PR 은 `_strip` 만 idiom 적응으로 끝냄. arity 일반 검증은 별 PR.
- **(F) — O (이번 PR).** `_strip` 시그니처 확장. LLM 의 `str.strip(chars)` 관용구 자연 지원.

## 자가 점검 (§6)
1. **자리**: F (transforms — 새 인자) + A (prompt 한 줄). LLM 관용구 silent fail 을 idiom 적응으로 해소.
2. **이전 케이스**: 없음 (transform arity silent dropout first time).
3. **누구 깰까**: 0. 기존 transforms 호출자 모두 `["strip"]` 형태 (arg 없음) 또는 미사용. `chars=None` 디폴트라 BC.
4. **검증**:
   - `apply_chain('/x/', [['strip','/']])` = `'x'` ✓
   - `apply_chain('  hi  ', [['strip']])` = `'hi'` ✓ (기존 동작)
   - probe_smoke PASS 272/0/4/0
   - 손-실행 list=10 body=11028 OK
5. **outcome=improved, fix_layer=F, commit prefix `[fix-layer: F]`**.
6. **fixture**: skip (기존 transforms 테스트 fixture 없음 — strip 케이스 하나만 박는 건 비대칭. 다음 transform 추가 시 testify 가치).
7. **트랙 B 매칭**: F (transforms 시그니처 확장) + A (prompt 명시) 2건. 별 PR 후보: (E) transform arity schema 검증, (C) extract_field 의 silent except → log/warn (silent dropout 자체가 future debug 시 hour 단위 소모).
