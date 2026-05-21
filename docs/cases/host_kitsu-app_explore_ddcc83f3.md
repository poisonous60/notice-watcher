---
slug: host_kitsu-app_explore_ddcc83f3
url: https://kitsu.app/explore/anime
status: 🔧 손 config (httpx_json) — Kitsu public edge API 사용
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [kitsu, anime, ember-shell, json-api, httpx-json]
---

## 무엇이 일어났나

`[FAIL] posts_nonempty: 0건`.

자동 생성은 `playwright_html`로 `a[href^='/anime/']`, `main a[href*='/anime/']` 계열 selector를 세 번 시도했지만 모두 0건이었다. probe의 정적 HTML 후보는 `head > link`, `head > meta`, `head > script`, `g > path`뿐이고 `first_article_url`도 없었다. 렌더 HTML은 Ember app shell이며 실제 anime row는 DOM selector로 안정적으로 잡히지 않았다.

preflight: b-hit — 실패 이후 영향 영역 commit(`27ed350`, `5665fa8`)이 있었지만 이 slug의 config/recognizer는 없었고, 현재 영향 영역의 미커밋 변경도 없었다.

screen-out: none — 단일 content page도 soft-404 shell도 아니다. `https://kitsu.app/explore/anime`는 브라우저 앱 경로로 살아 있고, HAR의 클릭 재시도에서 Kitsu edge API 호출이 확인됐다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)

`configs/host_kitsu-app_explore_ddcc83f3.json`을 추가했다.

- `strategy`: `httpx_json`
- `list.url_template`: `https://kitsu.app/api/edge/trending/anime?limit=20`
- `post_id`: API `id`
- `title`: `attributes.canonicalTitle`
- `url`: `https://kitsu.app/anime/{post_id}`
- `published_at`: `attributes.updatedAt`
- `summary`/본문: `attributes.synopsis`
- `cover_image`: `attributes.posterImage.medium`
- `polite_sleep`: 5~8초

robots 확인: `https://kitsu.app/robots.txt`와 `https://kitsu.io/robots.txt` 모두 `/api/`를 `Disallow`한다. 프로젝트 지침상 `register.py`는 이 경우 자동 거부가 아니라 경고로 다루므로, config에는 최소 호출 구조와 `polite_sleep`을 명시했다.

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행: list 3건, 첫 글 `One Piece`, body 1181 chars.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS.

## 트랙 B 검토

- 2a 인식기: X — Kitsu 전용 API endpoint이며 동일 플랫폼 반복 사례가 아직 없다.
- 2b first_article_url 교정: X — HTML에 글 링크가 없는 Ember shell이라 URL 후보 교정으로 풀 문제가 아니다.
- 2c/2d probe/schema/prompt: 보류 — HAR의 API 호출은 확인 가능하지만 `/api/` robots Disallow와 사이트 전용 endpoint 때문에 generic API 자동 채택 규칙으로 넓히기엔 위험하다.
- 2e 수동 config: 적용 — Kitsu edge API를 직접 지정하는 것이 가장 작은 변경이다.

일반화 안 되는 이유: Kitsu 전용 Ember shell + Kitsu edge API 조합이다. 같은 플랫폼/endpoint 케이스가 누적되기 전에는 recognizer나 API 자동 선택 규칙을 추가하지 않는다.
