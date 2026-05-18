---
slug: cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L
url: https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L
status: 🔧 손작성 config (작동중, baseline 33, handwritten/NaverCafeAdapter)
outcome: handcrafted
date: 2026-05-11
failure_keys: [posts_nonempty]
config_strategy: handwritten
adapters_changed: [NaverCafeAdapter]
vocab_candidates:
  - candidate: multi_api_merge
    confidence: high
    evidence:
      - adapters/navercafe.py:44-46
      - adapters/navercafe.py:LIST_API+NOTICE_API
      - case_feedback: "sticky 공지 API + 목록 API 두 응답을 합쳐서 list 반환. closed vocab httpx_json.list_path 는 단일 응답 단일 path 만."
    reasoning: "두 JSON API (공지 + 목록) 의 응답을 합쳐서 하나의 글 목록으로 반환해야 함. 현재 closed vocab 에 `list.url_template` list 받기 + `merge_strategy: concat|interleave` 같은 어휘 없음. multi-API 게시판 (네이버 카페·다음 카페 일부) 에 일반화 가치."
    analysis_date: 2026-05-18
    deferred: true
  - candidate: response_branch_body
    confidence: med
    evidence:
      - adapters/navercafe.py:_SKIP_ARTICLE_STATUS or 401/403 handler
      - case_feedback: "비공개·등급제한 게시판이면 본문 API 401/403 → 어댑터가 본문 비워 반환. 200 = 정상."
    reasoning: "글마다 본문 fetch 결과 status 분기 (200/401/403) 후 본문 합성/생략. closed vocab 의 article.fetch_kind 는 모든 글 동일 처리. Reddit·DaumCafe 동상 패턴."
    analysis_date: 2026-05-18
    deferred: true
---

## 무엇이 일어났나
`[FAIL] posts_nonempty: 0건` — 목록 추출이 0건. probe 가 글이 있는 건 알지만(first_article_url 잡힘) Gemini 의 `row_selector` 가 아무것도 못 잡음. **네이버 카페는 글 목록이 JS/iframe/내부 API 로 렌더**돼서 정적 HTML 에 글 행이 없음. → `config 자동생성 실패 케이스.md` §2a.

## 무엇을 바꿨나
손작성 `configs/cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L.json` — `strategy:"handwritten"`, `adapter:"NaverCafeAdapter"`, `kwargs:{cafe_id:30291108, menu_id:6, include_notices:true}`. `register.py --config <path>` 로 등록(baseline 33건, 공지 sticky 포함). 어댑터가 목록/공지/본문 JSON API(`apis.naver.com/cafe-web/...`, `article.cafe.naver.com/gw/...`)를 직접 호출. 비공개·등급제한 게시판이면 본문 API 가 401/403 → 어댑터가 본문 비워서 반환(우회 안 함), 그땐 storage_state 로그인 필요.

부수 수정: `register.py --config` 분기가 baseline state 를 직접 쓰면서 같은 slug 의 `.FAILED.json` 마커를 안 지우던 버그 → `_save_state()` 쓰도록 변경(마커 삭제 포함). 안 그러면 자동등록 한 번 실패했던 사이트는 `--config` 로 등록해도 봇 `_is_registered` 가 계속 False → `/preview`·`/watch` 가 또 자동경로(probe+gemini)로 돎.
