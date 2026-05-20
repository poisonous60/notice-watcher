---
slug: discourse_discuss.python.org_16ebc619
url: https://discuss.python.org/latest
status: ✅ 자동 (Discourse recognizer + DiscourseAdapter 신규 — JSON API 직접 호출)
outcome: handcrafted
date: 2026-05-20
fix_layer: F
failure_keys: [posts_nonempty, article_body_len]
config_strategy: handwritten
adapters_changed: [DiscourseAdapter]
engine_files_touched: [engine/recognizers/discourse.py, adapters/discourse.py, adapters/__init__.py]
tags: [discourse, platform-recognizer, json-api, batch-2026-05-20]
---

## 무엇이 일어났나

`catalog=2026-05-20` batch 결과 — Discourse 포럼 13 사이트 중 8 자동 등록, 5 실패:
- `discuss.python.org/latest` (rc=1, `posts_nonempty: 0건`)
- `discuss.huggingface.co/latest` (rc=1, `posts_nonempty: 0건`)
- `forum.djangoproject.com/latest` (rc=1, `posts_nonempty: 0건`)
- `forum.freecodecamp.org/latest` (rc=1, `posts_nonempty: 0건`)
- `users.rust-lang.org/latest` (rc=1, attempt 3 `playwright_html` 에서 `article_body_len: 0자`)

자동 성공 8건 (`discuss.elastic.co`, `discuss.streamlit.io`, `forum.bubble.io`, `forum.godotengine.org`, `forum.juce.com`, `forum.knime.com`, `internals.rust-lang.org`, `meta.discourse.org`) 도 일반 파이프라인이 *우연히* 정적 HTML 의 `tbody.topic-list-body` 를 잡았거나 RSS feed 폴백한 경우 — fragile.

진단:
- probe `list_candidates.json` 의 top 후보가 모두 `tbody.topic-list-body > tr.topic-list-item.category-<X>` 인데 child_count=6~8 (카테고리당). 정적 HTML 에 row 가 *어렴풋이* 있지만 LLM 이 그걸 안정적으로 못 잡음.
- attempt 3 (`discuss.python.org`) 가 `httpx_json list_path=['topic_list','topics']` 까지 도달 — `/latest.json` API 인식. 하지만 본문 fetch URL template 못 추측 → `article_body_len` fail.
- feed_candidates=2건 (RSS) — 백업 가능했으나 LLM 이 `httpx_html` 고집.

## 무엇을 바꿨나

### 1. `adapters/discourse.py` — `DiscourseAdapter` 신규
- `__init__(base_url, category_slug=None, category_id=None, timeout=15.0)`.
- `fetch_list`: `GET <base>/latest.json` 또는 `<base>/c/<cat>/<id>.json` → `topic_list.topics` 파싱.
- `fetch_article`: `GET <base>/t/<id>.json` → `post_stream.posts[0].cooked` (렌더된 HTML).
- 비공개/401/403/404 토픽은 빈 본문 반환 (우회 X).
- 429 백오프 3회.

### 2. `engine/recognizers/discourse.py` — recognizer 신규
- `NAME = "discourse"`.
- `PATTERNS = [(r"^https?://([^/?#]+)/latest/?(?:\?|#|$)", _build)]`.
- builder 가 cfg `{adapter:"DiscourseAdapter", kwargs:{base_url:"https://<host>"}}` 반환.
- `_slug_board = host` — 사이트별 distinguish.
- 오인 매칭 (`/latest` 가 Discourse 외 사이트) 안전망: DiscourseAdapter.fetch_list 가 `topic_list` 키 없으면 빈 목록 반환 → `register_recognized` 가 일반 파이프라인으로 폴백.

### 3. `adapters/__init__.py` — DiscourseAdapter export

### 4. 검증
- 5건 (discuss.python.org / forum.djangoproject.com / users.rust-lang.org / forum.freecodecamp.org / discuss.huggingface.co) 모두 `fetch_list 30건` + `fetch_article body chars ∈ [669, 4352]`. 정상.
- `recognize("https://example.com/latest")` 도 매칭 — 의도된 동작 (smoke 단계에서 자동 폴백).
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS (stage 1/2 의 stale fixture fail 은 pre-existing, hook 무관).

## 트랙 B 검토

- (2a) 인식기 — 이게 본 변경의 본질.
- (2b) `--article-url` 재시도 — 적용 X. Discourse 는 글 URL 패턴(`/t/<slug>/<id>`)이 *probe 가 잡긴 잡음*. 문제는 본문 fetch.
- (2c) probe 휴리스틱 — 신호는 이미 있음 (`tbody.topic-list-body`, `topic_list.topics`, feed_candidates). 휴리스틱화 가치 낮음 (LLM 이 결국 인식 못 함 → 손어댑터가 정답).
- (2d) probe 산출물 — 정상.

플랫폼 인식이 옳음. 13 catalog 사이트 + 미래 Discourse 사이트 모두 자동 처리.
