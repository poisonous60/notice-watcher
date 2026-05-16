# 사이트별 등록 시도 기록 — INDEX

> 자동 생성 — `python scripts/cases_index.py` 가 `docs/cases/*.md` 의 YAML frontmatter 를 모아 만든다. **직접 편집 X**.

총 15 건. 각 슬러그를 클릭하면 상세 case 파일.

| slug | status | date | fix_layer | failure_keys | url |
|---|---|---|---|---|---|
| [`naver-cafe_gutterlife_all_e0009e69`](cafe.naver.com_home.md) | ✅ 자동 (recognizer 확장 — cafe 홈 URL 인식, NaverCafeAdapter 가 cafe_slug→cafe_id 런타임 해소) | 2026-05-16 | F | posts_nonempty | https://cafe.naver.com/gutterlife |
| [`naver-cafe_31104609_1_c9b1f633`](naver-cafe_31104609_1_c9b1f633.md) | 🚫 등록 거부 (등록은 OK, 본문 추출 불가 — 정책상 우회 X) + 시스템 차원 후속 완료 | 2026-05-16 | F | body_empty_at_baseline, article_api_401_403 | https://cafe.naver.com/f-e/cafes/31104609/menus/1?viewType=L |
| [`host_scholar-google-_scholar_706d9c49`](host_scholar-google-_scholar_706d9c49.md) | 🔧 손 config (작동중, baseline 10, httpx_html) + (C) probe heuristic + (D) retry feedback hint | 2026-05-16 | C+D | article_body_len | https://scholar.google.com/scholar?hl=ko&as_sdt=0%2C5&q=harness&btnG= |
| [`host_ncs-go-kr_blind_ddd2b021`](host_ncs-go-kr_blind_ddd2b021.md) | ✅ 해결 (probe 룰 정정 + 손-config) | 2026-05-16 | C | classify_login_false_positive, baseline_ok_mismatch, posts_nonempty, post_id_unique | https://www.ncs.go.kr/blind/bl04/RecrtNotifList.do?searchNcsLclasCd=20&searchNcsMclasCd=01&searchNcsSclasCd=&searchNcsSubdCd=&searchStatus=&searchStartDt=&searchEndDt=&searchDstin=&searchType=&searchField=&searchCondition=0&searchKeyword= |
| [`host_google-com_search_9440e9f9`](host_google-com_search_9440e9f9.md) | 🛠 엔진 픽스 (silent hang 2 개 잡음 — subprocess 손자 pipe inherit + playwright sync_api close timeout 부재) | 2026-05-16 | F | silent_hang, subprocess_pipe_inherit, playwright_close_no_timeout | https://www.google.com/search?sa=X&sca_esv=d27b705f235d78cd&sxsrf=ANbL-n5nYxvvoLZQf_qvbJovw6dbr9D4Hw:1778909863391&udm=2&fbs=ADc_l-bD_nyrjATWBKup7flJ4rea5XFXsPHwMjGsTekJ1HCohBAQ3Hh19DqzlO7wr7YUgTdO4_C3uXoTo1-SRivc_Swap6of3IufrklCc-R1r_cYZiN4MoktmDvuiC1PeD4nH8f3b94UIye9mkD9gJ2OhVe3exK-hbmw6eC71bKU8Iww7ZBWxXDSN4anKuWYzQn_6P9msObToyspvu095YuigmETY6lXxzyOSC7CqTlAUcF0IYHKDC4&q=%EB%8C%80%EB%82%98%EB%AC%B4&ved=2ahUKEwjMufrTi72UAxWpia8BHQuuKc4QtKgLegQIERAB&biw=1707&bih=791&dpr=1.5 |
| [`host_syosetu-colomo-_root_2ff18e94`](host_syosetu-colomo-_root_2ff18e94.md) | 🚫 거부 (게시판 형식 아님 — 사전 게이트 추가) | 2026-05-15 | F | schema, row_required_selector | https://syosetu.colomo.dev/ |
| [`host_nte-perfectworl_kr_c8f4855a`](host_nte-perfectworl_kr_c8f4855a.md) | 🔧 손 config (작동중, baseline 3, httpx_html) | 2026-05-15 |  | article_body_len | https://nte.perfectworld.com/kr/article/news/index.html |
| [`www.reddit.com_r_CosmicPrincessKaguya`](www.reddit.com_r_CosmicPrincessKaguya.md) | 🧩 손어댑터 (작동중, baseline 19, handwritten/RedditAdapter, flair="Fan Art") | 2026-05-12 |  |  | https://www.reddit.com/r/CosmicPrincessKaguya/ |
| [`m.cafe.daum.net_umamusume-kor_Z4os_boardType`](m.cafe.daum.net_umamusume-kor_Z4os_boardType.md) | 🧩 손어댑터 (작동중, baseline 20, handwritten/DaumCafeAdapter) | 2026-05-12 |  | posts_nonempty | https://m.cafe.daum.net/umamusume-kor/Z4os?boardType= |
| [`mabinogimobile.nexon.com_News_notice`](mabinogimobile.nexon.com_News_notice.md) | 🔧 손작성 config (작동중, baseline 10) | 2026-05-11 |  | article_body_len | https://mabinogimobile.nexon.com/News/notice |
| [`game.naver.com_lounge_Trickcal_board_3`](game.naver.com_lounge_Trickcal_board_3.md) | 🔧 손작성 config (작동중, baseline 25, httpx_json) | 2026-05-11 |  | posts_nonempty | https://game.naver.com/lounge/Trickcal/board/3 |
| [`forum.nexon.com_bluearchive_board_list_board_1018`](forum.nexon.com_bluearchive_board_list_board_1018.md) | 🔧 손작성 config (작동중, baseline 30, httpx_json) | 2026-05-11 |  | posts_nonempty | https://forum.nexon.com/bluearchive/board_list?board=1018 |
| [`endfield_official`](endfield_official.md) | ✅ 손작성 config (작동중, baseline 20, httpx_json) | 2026-05-11 |  |  | https://web-news.gryphline.com/api/bulletin?lang=ko-kr&code=arknights_endfield_official |
| [`endfield.gryphline.com_ko-kr_news`](endfield.gryphline.com_ko-kr_news.md) | ✅ 자동등록 (작동중, baseline 20, httpx_json) | 2026-05-11 |  |  | https://endfield.gryphline.com/ko-kr/news |
| [`cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L`](cafe.naver.com_f-e_cafes_30291108_menus_6_viewType_L.md) | 🔧 손작성 config (작동중, baseline 33, handwritten/NaverCafeAdapter) | 2026-05-11 |  | posts_nonempty | https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L |

## 통계

### fix_layer 분포

| layer | count |
|---|---|
| (미기재) | 9 |
| C | 1 |
| C+D | 1 |
| F | 4 |

### config_strategy 분포

| strategy | count |
|---|---|
| (미기재) | 2 |
| handwritten | 5 |
| httpx_html | 3 |
| httpx_json | 4 |
| playwright_html | 1 |

### 최근 90일 (≥ 2026-02-15)

케이스 15 건.

