---
slug: host_plaync-com_ko-kr_a0ec8736
url: https://www.plaync.com/ko-kr/board/notice/list
status: "✅ view-link cluster 분류 개선 + PlayNC 공지 config 등록"
outcome: improved
date: 2026-05-26
fix_layer: A+C
failure_keys: [agent_self_veto_view_link_misclassified, kr_cms_view_url_pattern]
config_strategy: playwright_html
tags: [korean-cms, view-link, games-kr]
---

# PlayNC 공지 hand-config

## 증상

`https://www.plaync.com/news/` 자동 등록은 rc=3 gate reject 이후 agent self-veto `non_board` 로 끝났다. 사용자 제공 tail 기준으로 probe 는 실제 공지 글 URL `https://www.plaync.com/ko-kr/board/notice/view?articleId=6a0ac7005716f56bbe7ebce3` 를 찾았고, 같은 `/ko-kr/board/notice/view` 경로의 반복 링크가 `cc=18` 로 잡혔다.

로컬에는 `output/probe/host_plaync-com_news_3d3d95c4/` artifact 가 없었다. N100 pull/ssh 는 금지 범위라 수행하지 않았고, 사용자 제공 요약과 live PlayNC DOM 확인으로 재현했다.

## 원인

post-fail classifier 의 구조 힌트가 `href_pattern_guess` 에서 path 만 출력해 query string 을 버렸다. 그 결과 `view?articleId=<id>` 형태의 글 상세 링크 묶음이 단순 `/view` path cluster 로 축약되어 nav/section/picker cluster 처럼 보였고, agent 가 `clean article cluster 0` 으로 오판했다.

이 패턴은 site-specific 이 아니라 KR CMS 전반에 있는 detail URL 구조다. `/board/<name>/view?articleId=<id>`, `/bbs/view.do?seq=<id>`, `/notice/view?id=<id>` 처럼 같은 path 에 query id 만 달라지는 링크는 목록의 article cluster 로 취급해야 한다.

## 변경

- `generate/classify.py`: detail path segment(`view`, `detail`, `article`, `post`)와 id-like query param(`articleId`, `seq`, `id`, `no` 등)이 같이 반복되면 `view-link cluster ... = article cluster` 로 구조 힌트에 명시한다. debug top 에도 `?articleId=<id-like> (view-link cluster)` 가 남는다.
- `prompts/config_writer.system.txt`: self-veto 예외 1줄 추가. 같은 path + id-like query detail-view 패턴이 3개 이상 반복되면 `non_board` 로 멈추지 말고 config 작성을 계속한다.
- `configs/host_plaync-com_ko-kr_a0ec8736.json`: 실제 공지 URL `/ko-kr/board/notice/list` 기준 `playwright_html` config 추가. N100 headless 기본값을 깨지 않도록 `headless: false` 는 넣지 않았다.

## PlayNC config

렌더된 목록은 `div.board` row 안에 `a.title[href*='/ko-kr/board/notice/view?articleId=']` 제목 링크와 `span.posted-at` 날짜를 가진다. 글 본문은 detail page 의 `div.view-body` 에 렌더된다.

검증 결과:

```text
list 10
6a0ac7005716f56bbe7ebce3 '5월 20일(수) 정기 점검 안내'
6a018c805a13e9294581518c '5월 13일(수) 정기 점검 안내'
6a018af12ca56442e29e8744 '[완료] 카카오페이 정기구독 서비스 일시 중단 안내'
body 4164
```

`python scripts/register.py --config "configs/host_plaync-com_ko-kr_a0ec8736.json"` 결과:

```text
✅ 등록 완료 — baseline 18건
6a0ac7005716f56bbe7ebce3  2026-05-18T00:00:00+09:00  5월 20일(수) 정기 점검 안내
```

## 회귀 검증

- 분류기 단위 테스트에 synthetic PlayNC-style fixture 추가: repeated `/ko-kr/board/notice/view?articleId=<hex>` cluster 가 `view-link cluster 2종 = article cluster` 로 표시된다.
- 영향 범위는 classifier 구조 힌트 문자열과 config writer system prompt 1줄이다. 기존 config 실행 경로와 selector engine 은 변경하지 않았다.

## 일반화

이 변경은 특정 PlayNC selector 가 아니라 `same path + detail segment + id-like query` 구조를 article cluster 로 보존한다. egov, XPressEngine, iBoard 류 CMS 에서 query string 에 글 ID를 싣는 목록을 nav hub 로 오분류하는 위험을 줄인다.

## 보류/제외

- `/news/` probe artifact replay 는 로컬 artifact 부재로 수행하지 않았다. SSH/tar pull 은 금지 범위라 defer 한다.
- `scripts/cases_index.py`, `docs/cases/INDEX.md`, `output/cases.sqlite3` backfill 은 실행하지 않았다.
- `probe/`, `engine/recognizers/`, `scripts/register.py`, `prompts/classify.system.txt` 는 건드리지 않았다.
