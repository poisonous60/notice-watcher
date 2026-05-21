---
slug: host_df-nexon-com_community_cae73546
url: https://df.nexon.com/community/news/notice/list
status: ✅ 수동 config (작동중, baseline 21, httpx_html)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [nexon, df, handcrafted]
---

## 무엇이 일어났나

`triage.py show` 기준 자동 생성은 `[FAIL] posts_nonempty: 0건` 으로 3회 실패했다. 직전 config 는 `article.board_list.news_list > ul` 을 바라봤지만, probe artifact 의 `list.html` 은 실제 공지 목록이 아니라 `<title>점검페이지</title>` 인 점검/이벤트성 HTML 이었다. 그래서 digest 는 `operation_guide`, `cartoon`, `swiper` 같은 부가 UI를 반복 후보로 올렸고, `inline_js_data_candidates=1` 도 실제 공지 데이터가 아니라 `pattyStack` 게임 스크립트 오탐이었다.

현재 live HTML 을 직접 확인하면 공지 목록은 정적 HTML 로 내려온다. `article.board_list.news_list > ul` 행 안에 `li.title[data-no]`, 제목 링크, 날짜, 카테고리가 모두 있다. 실패 원인은 JSON island 누락이 아니라 실패 당시 probe artifact 오염이다.

## 무엇을 바꿨나

`configs/host_df-nexon-com_community_cae73546.json` 을 손작성했다.

- strategy: `httpx_html`
- 목록: `https://df.nexon.com/community/news/notice/list`
- row: `article.board_list.news_list > ul`
- post_id: `li.title[data-no]`
- title/url/category: 같은 행의 `li.title a`, `li.category`
- published_at: 목록에서 `YYYY.MM.DD` 형식만 파싱한다. 당일 글은 `14:29` 처럼 시간만 나오므로 목록 날짜는 비워두고, 글 본문의 `.sinfo .date` 가 `YYYY.MM.DD HH:MM` 을 제공할 때 보강한다.
- 본문: `div.board_view.news_view div.bd_viewcont div.operation_guide` 우선, 없으면 `div.bd_viewcont`.

기존 `engine/recognizers/nexon_forum.py` 는 `forum.nexon.com/{game}/board_list?board=...` 전용 공개 API recognizer 다. `df.nexon.com/community/news/...` 는 호스트와 URL 구조가 달라 이번 변경에는 확장하지 않았다.

## 검증

- `validate_config` OK.
- `make_adapter().fetch_list(page=1)` → 10건, 첫 글 본문 2444자.
- `python scripts/register.py --config "configs/host_df-nexon-com_community_cae73546.json"` → 등록 완료, baseline 21건.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 839 / FAIL 0.
- `python scripts/vocab_lint.py` → OK.

## 트랙 B 검토

- (2a) recognizer: `df.nexon.com` 내부 여러 뉴스 보드가 비슷할 수는 있지만, 이번 요청 URL 하나는 정적 HTML config 로 충분하다. `nexon_forum.py` 와는 다른 플랫폼이라 기존 recognizer 확장은 보류했다.
- (2c/A) probe/prompt: `inline_js_data_candidates` 가 false-positive (`pattyStack`) 였고, artifact 자체가 점검페이지라 일반화 신호로 쓰기 어렵다. probe/prompt 보강은 HARD-STOP allow-list 밖이라 변경하지 않았다.
- 일반화 안 되는 이유: live 사이트는 이미 정적 HTML 로 풀리며, 실패 artifact 오염을 단일 config 로 회수하는 케이스다.
