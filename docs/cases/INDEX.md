# 사이트별 등록 시도 기록 — INDEX

> 자동 생성 — `python scripts/cases_index.py` 가 `docs/cases/*.md` 의 YAML frontmatter 를 모아 만든다. **직접 편집 X**.

총 11 건. 각 슬러그를 클릭하면 상세 case 파일.

| slug | status | date | fix_layer | failure_keys | url |
|---|---|---|---|---|---|
| [`naver-cafe_31104609_1_c9b1f633`](naver-cafe_31104609_1_c9b1f633.md) | 🚫 등록 거부 (등록은 OK, 본문 추출 불가 — 정책상 우회 X) | 2026-05-16 | none | body_empty_at_baseline, article_api_401_403 | https://cafe.naver.com/f-e/cafes/31104609/menus/1?viewType=L |
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
| F | 1 |
| none | 1 |

### config_strategy 분포

| strategy | count |
|---|---|
| (미기재) | 1 |
| handwritten | 4 |
| httpx_html | 2 |
| httpx_json | 4 |

### 최근 90일 (≥ 2026-02-14)

케이스 11 건.

