---
slug: game.naver.com_lounge_Trickcal_board_3
url: https://game.naver.com/lounge/Trickcal/board/3
status: 🔧 손작성 config (작동중, baseline 25, httpx_json)
outcome: handcrafted
date: 2026-05-11
failure_keys: [posts_nonempty]
config_strategy: httpx_json
---

## 무엇이 일어났나
봇 `/preview`: `[FAIL] posts_nonempty: 0건` ( + `[warn] count_ballpark: 0건 (probe child_count≈52)`). 네이버 게임 라운지는 React + CSS-modules 라 목록/본문 클래스가 `post_board_detail__1JkwM` 같은 해시 — Gemini 가 그 selector 로 httpx_html config 를 만들었지만 정적 HTML 엔 그 행이 없음(서버는 SEO용 일부만, 실제 목록은 내부 API). probe 의 `traffic_json_api_candidates` 휴리스틱이 그 API 를 못 골라서(후보 0건) 자동으론 httpx_json 으로도 못 감. → `config 자동생성 실패 케이스.md` §2a.

## 무엇을 바꿨나
probe HAR 에서 직접 찾은 내부 API 로 손작성 `configs/game.naver.com_lounge_Trickcal_board_3.json` (`httpx_json`):
- 목록 `https://comm-api.game.naver.com/nng_main/v1/community/lounge/Trickcal/feed?boardId=3&buffFilteringYN=N&limit=25&offset=0&order=NEW` — `success_when code==200`, `list_path: ["content","feeds"]`, 엔트리 안에 `feed`/`user`/`feedLink`/`board` 서브객체 (post_id=`feed.feedId`, title=`feed.title`, url=`feedLink.pc`, author=`user.nickname`, category=`board.boardName`, published_at=`feed.createdDate`→`iso8601 %Y%m%d%H%M%S`, cover=`feed.repImageUrl`). offset 페이징(`offset_param:offset`, `page_unit:25`).
- 본문 `https://comm-api.game.naver.com/nng_main/v1/community/lounge/Trickcal/feed/{post_id}` — `fetch_kind:json`, `data_path:["content"]`, content=`feed.contents` (SmartEditor 렌더 HTML). (목록 쪽 `feed.contents` 는 SE *JSON* 이라 안 씀 — 단일-feed 엔드포인트가 HTML 로 렌더해 줌.)
- 헤더: UA + `front-client-platform-type:PC` + `front-client-product-type:web` + `Referer`/`Origin` 이면 200 (deviceid·cookie 불필요). 같은 라운지 다른 게시판은 `boardId`·`Referer` 만 교체하면 됨 → 다른 게임 라운지도 같은 패턴.
- sticky pin 글(`.../feed/pins?boardId=3`, 응답이 bare list)은 라운지 전역 홍보글이라 제외 — board 3 자체 글만.
