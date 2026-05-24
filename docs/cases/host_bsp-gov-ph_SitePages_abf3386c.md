---
slug: host_bsp-gov-ph_SitePages_abf3386c
url: https://www.bsp.gov.ph/SitePages/MediaAndResearch/MediaDisp.aspx
status: "수동 config - BSP SharePoint JSON API"
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, sharepoint_list_api]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [bsp, sharepoint, json-api, media-releases]
---

## 무엇이 일어났나

`register.py` 자동 생성은 `playwright_html` config 를 3회 시도했지만 모두
`[FAIL] posts_nonempty: 0건` 으로 실패했다. probe digest 는 `verdict=정적 HTTP로 충분` 이지만
`list_candidates.json` 에는 `head > script`, `head > meta` 같은 반복 후보만 있고
`first_article_url` 은 없었다.

HAR 를 확인하니 렌더된 SharePoint 페이지가 실제 목록을 다음 공개 API에서 가져온다.

`/_api/web/lists/getByTitle('Media%20Releases%20and%20Advisories')/items`

목록 API의 `value[]` 항목은 `Id`, `Title`, `PDate`, `Content`, `Tag` 를 포함한다. 정적 HTML selector 나
Playwright selector 미세 조정이 아니라 SharePoint list API 를 직접 쓰는 쪽이 안정적이다.

## 픽스

`configs/host_bsp-gov-ph_SitePages_abf3386c.json` 을 `httpx_json` config 로 작성했다.

- 목록: `Media Releases and Advisories` SharePoint list API, `PDate desc`, 최대 30건
- `post_id`: `value[].Id`
- `title/published_at/category`: `Title`, `PDate`, `Tag`
- 사용자 링크: 기존 화면 URL `MediaDisp.aspx?ItemId={post_id}&MType=MediaReleases`
- 본문: 같은 SharePoint list API에서 `Content` 필드를 `article.content` 로 추출
- `polite_sleep`: 5-7초

## 트랙 B 검토

- **2a (recognizer) - 보류.** SharePoint API 패턴은 보이지만 list title, filter, status field, article page URL
  조합이 BSP 사이트에 묶여 있다. 이 단건만으로 generic SharePoint recognizer를 만들면 다른 SharePoint 사이트의
  list title 또는 moderation/status 관례를 잘못 가정할 위험이 크다.
- **2b (`--article-url`) - X.** 첫 글 URL 교정 문제가 아니라 목록 row 자체가 정적 HTML에 없는 문제다.
- **2c/2d (probe/engine) - 보류.** HAR에 `_api/web/lists/getByTitle(...)` 신호가 있으나 현재 자동 후보는
  item shape와 site-specific filter를 판단하지 못한다. 같은 root-cause가 누적되면 SharePoint API 후보 추출을
  별도 track B로 설계할 수 있다.
- **2e (수동 config) - O.** 한 slug를 작동시키는 최소 변경은 config 1개다.

## 회귀 검증

- `python -c "import json; from engine.config_schema import validate_config; validate_config(json.load(open(r'configs/host_bsp-gov-ph_SitePages_abf3386c.json',encoding='utf-8'))); print('OK')"`
- `make_adapter` 스모크: `fetch_list(page_size=5)` 5건, 첫 글 본문 HTML 2768자
- `python scripts/probe_smoke.py --stage 3 --stage 5`
- `python scripts/register.py --config configs/host_bsp-gov-ph_SitePages_abf3386c.json`

## 자가 점검

1. **자리**: config only. adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 누적은 많지만 `sharepoint_list_api` 는 이번 단건에서 첫 기록.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 사이트 영향 없음.
4. **outcome=handcrafted**: BSP SharePoint list title과 filter를 박은 단일 사이트 config다.
5. **INDEX/DB**: 이번 Codex 작업에서는 `cases_index.py`, `--backfill-db`, `docs/cases/INDEX.md`,
   `output/cases.sqlite3` 를 건드리지 않는다.
