---
slug: forum.nexon.com_bluearchive_board_list_board_1018
url: https://forum.nexon.com/bluearchive/board_list?board=1018
status: 🔧 손작성 config (작동중, baseline 30, httpx_json)
outcome: handcrafted
date: 2026-05-11
failure_keys: [posts_nonempty]
config_strategy: httpx_json
engine_files_touched: [engine/transforms.py]
---

## 무엇이 일어났나
봇 `/preview`: `[FAIL] posts_nonempty: 0건` ( + `[warn] matches_probe_first_article` / `count_ballpark 0건`). 넥슨 포럼 `board_list` 는 사실 정적 HTML 로 행이 다 들어있는데(`ul.type-list > li`, 15건), probe 가 "첫 글"로 사이드바 서브게시판 링크(`board_list?board=1618`)를 잡아버려서 Gemini 가 만든 httpx_html config 가 어긋남 — 그리고 본문 URL 로는 존재하지 않는 `…/api/v1/community/bluearchive/thread/{id}` 를 추측(404). → `config 자동생성 실패 케이스.md` §2a 변형(정적 HTML 인데 probe 의 first_article 휴리스틱이 메뉴 링크를 글로 오인).

## 무엇을 바꿨나
HAR 에서 찾은 공개 JSON API 로 손작성 `configs/forum.nexon.com_bluearchive_board_list_board_1018.json` (`httpx_json`):
- 목록 `https://forum.nexon.com/api/v1/board/{board}/threads?alias=bluearchive&paginationType=PAGING&pageSize=30&blockSize=5&hideType=WEB` — `list_path: ["threads"]`, sticky 공지도 이 응답에 `isSticky:true` 로 같이 옴(별도 `stickyThreads` 엔드포인트 불필요). post_id=`threadId`, title=`title`(HTML 이스케이프됨→`html_unescape`), url=template `https://forum.nexon.com/bluearchive/board_view?board={board}&thread={post_id}`, published_at=`createDate`(unix epoch 초→`unixtime_to_iso +09:00`), author=`user.nickname`, summary=`summary`, cover=`thumbnailImageUrl`. `pageNo` query_param 페이징.
- 본문 `https://forum.nexon.com/api/v1/thread/{post_id}?alias=bluearchive` — `fetch_kind:json`, content=`["content"]`(렌더 HTML), `re_extract:true`(본문 응답이 title/summary/createDate/user/thumbnail 동일 키라 메타 보강). 본문 fetch ~10k자 확인.
- 헤더: UA + `Accept: application/json...` + `X-Requested-With: XMLHttpRequest` + `Referer`. 같은 넥슨 포럼의 다른 게임/게시판은 `alias`(=게임코드)·`board`(=boardId)·`Referer` 만 바꾸면 동일 패턴.
- 부수: `engine/transforms.py` 에 `html_unescape` transform 추가(`html.unescape` 래퍼) — JSON API 가 제목/요약을 HTML 이스케이프해 주는 사이트 일반용.

## 후속 (2026-05-12)
이 "probe 가 첫 글을 메뉴 링크로 오인" 케이스를 계기로 `register.py --article-url "<글URL>"` + 봇 `/preview`·`/watch` 의 `article_url` 인자 추가 — 사용자가 진짜 글 URL 을 주면 first_article_url 교정 + 그 글페이지 render+HAR re-probe + 강한 hint 로 처음부터 재생성. (`config 기반 엔진 가이드.md` §4 / `config 자동생성 실패 케이스.md` §2a·§5.)
