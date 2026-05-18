---
slug: m.cafe.daum.net_umamusume-kor_Z4os_boardType
url: https://m.cafe.daum.net/umamusume-kor/Z4os?boardType=
status: 🧩 손어댑터 (작동중, baseline 20, handwritten/DaumCafeAdapter)
outcome: handcrafted
date: 2026-05-12
failure_keys: [posts_nonempty]
config_strategy: handwritten
adapters_changed: [DaumCafeAdapter]
vocab_candidates:
  - candidate: inline_js_array_scrape
    confidence: high
    evidence:
      - adapters/daumcafe.py (fetch_list — `articles.push({...})` JS 블록 regex 파싱)
      - case_feedback: "글 데이터가 페이지 인라인 JS `articles.push({dataid,fldid,title,...})` 형태. json.loads 불가 (JS literal). probe 의 hydration 휴리스틱이 `__NEXT_DATA__` / `__INITIAL_STATE__` 같은 JSON 리터럴만 잡아서 못 봄."
    reasoning: "JS `funcName.push({...})` 호출 패턴에서 객체 리터럴 regex 추출. closed vocab 의 `from:json` source 는 진짜 JSON 응답만 처리. inline JS array scrape 어휘 추가 가치 (다음 카페 외 옛 SSR + 인라인 JS 사이트)."
    analysis_date: 2026-05-18
    deferred: true
  - candidate: response_branch_body
    confidence: not_applicable
    evidence:
      - adapters/daumcafe.py:202 (`if r.status_code in _SKIP_ARTICLE_STATUS:` — status only)
      - case_feedback: "비공개/등급제한 카페·게시판이면 401/403 → 본문 비워 반환 (NaverCafe 와 동일)."
    reasoning: "재분류 2026-05-18 (vocab-ext design doc 검토 결과): 본문 분기가 status only — 기존 `article.skip_status: [401, 403]` 어휘로 표현 가능. 새 어휘 불필요. (DaumCafe 의 진짜 신규 패턴 = `inline_js_array_scrape` — 별 후보로 이미 등록됨)"
    analysis_date: 2026-05-18
    reclassified_at: 2026-05-18
    reclassified_reason: "skip_status 재사용으로 OK — reviewer subagent 코드 확인 (line 202)"
    deferred: false
---

## 무엇이 일어났나
봇 `/preview`: `[FAIL] posts_nonempty: 0건`. 다음카페 모바일 게시판 페이지는 정적 httpx GET 으로 200(Cloudflare 없음)이고 글 행이 `<li>` 로 렌더돼 있긴 한데 **그 `<a>` 의 href 가 `javascript:` (`class="link_cafe make-list-uri"` — 클릭 시 JS 가 URL 생성)** 라서 자동 파이프라인이 post_id/url 을 못 뽑음 → Gemini 가 `playwright_html` + `ul.list_cafe#slideArticleList > li` 로 만들었지만 0건(그 selector 는 썸네일 캐러셀이고, 어차피 href 가 javascript:). 게다가 본문 `url_template` 으로 **카카오 광고 배너 URL**(`display.ad.daum.net/sdk/banner?...`)을 골라버림(probe 의 JSON API 후보 휴리스틱이 광고 SDK 호출을 본문 API 로 오인). 실제 글 데이터는 페이지 안 인라인 JS `var articles=[]; articles.push({dataid, fldid, title, writerNickname, articleElapsedTime, headCont, viewCount, commentCount, thumbnailImageUrl, ...})` 에 있음 — `__NEXT_DATA__` 같은 JSON 리터럴이 아니라 `articles.push(...)` 형태라 probe 의 hydration 추출도 못 잡음. → `config 자동생성 실패 케이스.md` §2a(목록이 인라인 JS).

## 무엇을 바꿨나
손어댑터 `adapters/daumcafe.py` `DaumCafeAdapter`(`adapters/__init__.py` `__all__` 등록) — `kwargs:{cafe_name:"umamusume-kor", board_id:"Z4os"}`. 정적 GET `m.cafe.daum.net/<cafe>/<board>?boardType=` → 페이지 HTML 에서 `articles.push({...})` 블록을 regex 로 필드별 파싱(JS 라 json.loads 불가; 문자열은 `json.loads('"'+raw+'"')` 로 이스케이프 해석). post_id=`dataid`, url=`m.cafe.daum.net/<cafe>/<fldid>/<dataid>`, title=`[headCont]title`, author=`writerNickname`, category=`headCont`, published=`articleElapsedTime`(`YY.MM.DD`→ISO / `HH:MM`→오늘+시각). 본문은 그 url 정적 HTML — 컨테이너 `div#article.tx-content-container`(fallback `div#article`/`div.tx-content-container`), 제목 `h3.tit_subject`(말머리 `[..]` 포함), 날짜 `span.num_subject`. 401/403(비공개·등급제한)이면 본문 비워 반환(우회 안 함). 페이지네이션은 모바일 카페가 무한스크롤이라 page 1(~20건)만 — 공지 게시판엔 충분. `register.py --config` 로 등록(baseline 20). 같은 다음카페의 다른 게시판은 `cafe_name`·`board_id` 만 바꾸면 동일.

## 후속 (2026-05-12)
이 건을 계기로 `engine/known_platforms.py` 추가 — register.py 가 probe 전에 URL 을 알려진 플랫폼 패턴에 매칭시켜 config 를 즉시 생성(probe/Gemini 생략, 잘못 매칭하면 fetch_list 0건일 때 폴백). 현재 인식: 네이버 카페·다음 카페·아카라이브·디시 미니갤·넥슨 포럼·네이버 게임 라운지·Reddit. 같은 플랫폼의 다른 게시판은 이제 `/watch`·`/preview` 만으로 등록됨. (`config 기반 엔진 가이드.md` §1 "register.py 의 처리 순서".) **2026-05-15**: `engine/known_platforms.py` 는 commit `86437a2` 에서 `engine/recognizers/` 패키지로 분리됨 — auto-discovery (`engine/recognizers/<plat>.py` 파일 한 개 추가 시 자동 등록).
