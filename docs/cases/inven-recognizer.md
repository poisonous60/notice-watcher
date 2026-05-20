---
slug: inven-recognizer
url: https://www.inven.co.kr/board/lol/4625
status: ✅ recognizer 승급 (cluster 6건 → engine/recognizers/inven.py)
outcome: improved
date: 2026-05-20
failure_keys: []
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/inven.py]
---

## 무엇이 일어났나
인벤(inven.co.kr) 게시판 6건이 개별 LLM 생성됨 (실제 board/url):
`ff14/4467` · `party/6510` · `lostark/4811` · `maple/2304` · `lol/4625` · `party/6181`.
(승급 요청 시 제시된 URL 중 lol/3582·wow/4625·webzine/news 3건은 stale — 실제 config 의 board 값과 불일치.
실제 url_template/board 를 기준으로 재정의.)

hoyolab 과 달리 **byte-동일이 아님**. 6 config 가 같은 사이트를 제각기 다르게 캡처:
- url_template 표현 3종 (`/board/ff14/4467` 리터럴 · `/board/party/{board}` · `/board/{board}`)
- post_id 2전략 (`td.num span` 텍스트 vs `a.subject-link` href regex)
- title 3전략 (plain · concat[category+title] · replace-bracket-tags)
- row_selector 4종, 헤더 (Sec-CH-UA·Referer 유무) 제각각

## 핵심 판단 — "2 site types?" → 라이브 probe 로 단일 CMS 확인
사용자 직관: "사이트가 2종류 있는 것 같다". noisy config 만 보면 그렇게 보임.
→ 추측 대신 6개 board 를 **라이브 fetch** 해서 실제 DOM 비교:
- list: 6개 모두 `form[name=board_list1]` / `tbody>tr` / `td.num span` / `a.subject-link`, href `=/board/<game>/<id>/<post_id>` — **동일**.
- article: 6개 모두 `#powerbbsContent` + `div.articleView div.articleMain` + `div.articleContent` **전부 존재**(중첩) — **동일**.

결론: `/board/<game>/<id>` 는 **단일 CMS DOM**. 6 config 의 차이는 동일 페이지에 대한 LLM noise.
(인벤의 *진짜* 2번째 타입 = `/webzine/` — 별 DOM. 단 이 6건 중 webzine 을 가리킨 멤버는 없음. "webzine" 명 멤버는 실제 `/board/party/6181`.)

## 무엇을 바꿨나
어느 noisy 멤버도 canonical 로 채택하지 않고 **라이브 검증한 selector 로 새로 합성** → `engine/recognizers/inven.py`:
- 정규식 `//(?:www\.)?inven\.co\.kr/board/([^/?#]+)/(\d+)(?:[?#]|/?$)` — game + board_id 두 변수 path 추출.
  board_id 뒤 `/(\d+)` (개별 글 segment) 면 매칭 X → 목록만, 글 URL 제외.
- builder: list `form[name=board_list1] tbody>tr`, post_id=`a.subject-link` href 숫자(공지 행도 견고), title/url=`a.subject-link`, author=`td.user .layerNickName`, category=`a.subject-link .category`, date=`td.date`(오늘 `HH:MM`|그외 `MM-DD`, iso8601 순서 시도). article content fallback `#powerbbsContent`→`articleView`→`contentBody`, enrich title/date(`%Y-%m-%d %H:%M`)/author.
- `_slug_board=<game>_<board>` (slug 안정).

## 효과
- 이후 인벤 게시판(어느 game/board 든) 등록 → probe/Gemini 생략, 결정적 생성 = **토큰 0 + LLM noise 0**.
- cluster_report 재실행 시 inven 후보 자동 소멸 (live `recognize()` 억제).
- 기존 6 config 손 안 댐 (slug 마이그 X, Rule D 회피). recognizer 는 이후 등록부터.

## 회귀 검증
```
$ PYTHONPATH=. python tests/recognizers/test_inven.py
  15 passed  (extract×6 / field_shape / no_www / query_suffix / recognize_integration /
              other_host_negative / same_host_neg×4[개별글·webzine·그룹·포털])

$ 라이브 e2e — recognize → ConfigAdapter.fetch_list/fetch_article (lol/4625)
  list items=8 (post_id/title/url/author/category 정상)
  article content_html=11097 chars (#powerbbsContent), title/author/category 정상

$ recognize_reject(멤버 url×3) → 전부 None  (article_page_reject 와 안 겹침)

$ scripts/cluster_report.py  # 봉합
  recognized 35→40 · [A] SAME-HOST 에서 inven 후보 소멸 (github·steam 만 남음)
```

## 알려진 한계 (멤버 공통 — 신규 아님)
list `td.date` 에 연도가 없어 `published_at` 이 `1900-MM-DD`/`1900-01-01THH:MM` 로 파싱됨 (cosmetic).
신규-글 감지는 단조 증가 post_id 로 하므로 영향 없고, article enrich 는 `%Y-%m-%d %H:%M` 풀 연도 → 정확.
기존 inven 멤버(maple `%m-%d` 등)도 동일 동작 — recognizer 가 도입한 회귀 아님.

## 슬러그 drift 중복 폴링 봉합 (후속)
recognizer 추가 = 같은 board URL 의 slug 파생 규칙 변경(Rule D 상황). 기존 6 멤버는 옛 fallback slug
(`host_inven-co-kr_board_<hash>`)로 등록돼 있고, recognizer 적용 후 같은 URL 은 `inven_<game>_<board>_<hash>`.
slug 다름 → 같은 board 가 2번째 config 로 중복 등록·폴링 → 같은 사람이 양쪽 구독 시 새 글 2번 알림 위험.

봉합(prevention): `bot/site_ops.find_registered_alias(url)` — canonical_url 신원으로 기존 등록 slug 역조회.
`/watch`·`/preview`·worker register 가 enqueue/등록 전 alias 흡수(기존 slug 재사용), `/unwatch`(URL)는 old/new
양쪽 제거. 모든 platform·미래 recognizer 공통 게이트. (codex 리뷰 반영: unwatch 양쪽 제거 버그, worker race 가드 추가.)

남은 한계(미구현, 의도): *이미 양쪽 등록된* 과거 중복의 사후 정리(migration)·notify-level canonical dedup 은 안 함 —
현재 6 board 는 new-slug config 가 아직 없어 중복 없음. prevention 으로 충분, 사후 정리는 필요 시 별도.

## 비고
2번째 recognizer-extension 실증 (hoyolab 다음). hoyolab=byte-동일(쉬움), inven=구조 divergent(어려움) 케이스.
divergent 일 때 표준 round-trip(멤버 재현)은 적용 불가 → URL 추출 + 라이브 e2e + same-host negative 로 대체.
설계·검증: 2026-05-20 dev box session.
