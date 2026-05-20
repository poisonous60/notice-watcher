---
slug: steam-news-recognizer
url: https://store.steampowered.com/feeds/news/app/730/
status: ✅ recognizer 승급 (cluster 10건 → engine/recognizers/steam_news.py)
outcome: improved
date: 2026-05-20
failure_keys: []
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/steam_news.py]
---

## 무엇이 일어났나
자동생성된 개별 config 12건이 N100 `configs/host_store-steampowe_feeds_*.json` 에 쌓임 (dev 박스엔 없었음 —
사용자 `/watch` 등록이 N100 에서 동작, Rule C 비대칭. 승급 위해 `scp` 로 12건 dev 박스에 내려받아 commit —
동시에 dev↔N100 config sync).

12건은 **3개 family**:
- **`/feeds/news/app/<appid>/` 10건** (105600·440·570·730·294100·413150·570·1086940·1091500·1145360·1245620) —
  Steam 앱 뉴스 RSS. appid 만 URL 변수. → recognizer 승급 대상.
- `/feeds/daily_deals.xml` 1건 (b53837a7) — RDF, appid 슬롯 **없음**, `row_selector="item"`, 구조 다름. **제외**.
- `/feeds/news.xml` 1건 (9e4f1bed) — 전역 뉴스, post_id=rdf:about regex, title=`"Steam News {id}"` 템플릿. **제외**.

## 무엇을 바꿨나
recognizer-extension 스킬로 10건 cluster → `engine/recognizers/steam_news.py` (`NAME=steam-news`):
- **2개 정규식** (둘 다 같은 builder, appid → 같은 피드 config 로 정규화):
  - `_RE_FEED`: `//store\.steampowered\.com/feeds/news/app/(\d+)/?(?:[?#].*)?$` — RSS 피드 URL.
  - `_RE_HUB`: `//store\.steampowered\.com/news/app/(\d+)/?(?:[?#].*)?$` — HTML 허브 URL.
    **사람이 브라우저에서 복사하는 건 허브 URL** 이라 추가 — 입력이 허브여도 `list.url_template` 은 피드(`/feeds/news/app/{board}/`)로 빌드해 RSS 를 폴링.
  - **end-anchor** 가 `.../view/<id>`(개별 article) 배제. daily_deals.xml·news.xml 은 `/news/app/` 아니라 자동 배제.
- builder: `board=appid` 를 URL path 에서 추출 (저장된 `board` 신뢰 X — 570 은 `"app/570"` malformed). `_slug_board=appid`.
  list/article skeleton 은 appid 불문 동일한 canonical 상수 (행 `channel > item`, post_id guid `/view/(\d+)`,
  title `<title>`, pubDate RFC822 `%a, %d %b %Y %H:%M:%S %z`, summary `description`(html_unescape),
  cover `enclosure[url]`, 본문 `div.news_postbody` 등 5종 fallback).

### round-trip 모델 — byte-match 안 함 (hoyolab 와 다름, github-releases 와 같음)
10건은 LLM 이 멤버마다 다른 헤더(sec-ch-ua·Referer·polite_sleep)·url transform(strip_brackets·urljoin)·
article selector·enrich·include_notices 를 뽑아 **서로/canonical 과 다름**. RSS 구조는 appid 불문 동일 →
교정한 canonical selector 하나로 충분. 따라서 검증을 "기존 재현" 대신:
- 멤버 URL(=`list.url_template` 에 `board` 치환) → `board=appid`·`url_template` 결정적 추출 (app-feed 10건 전수, anti-vacuous ≥10 강제)
- app-feed 아닌 멤버(daily_deals.xml, news.xml) → builder `None` (cluster 제외 확인)
- 허브 URL → 피드 config 로 정규화 (board·url_template 검증)
- 같은-host 다른-종류 negative (daily_deals·news.xml·`/news/app/<id>/view/<id>`·`/feeds/news/app/<id>/view/<id>`·`/app/<id>/`) → `recognize()` 미매칭
- reject 충돌: `recognize_reject(피드 URL)` == None

## 효과
- 이후 Steam 앱 뉴스(어느 appid든, 피드·허브 URL 둘 다) 등록 → probe/Gemini 생략, builder 결정적 생성 = **토큰 0 + 실패 없음**.
- 모든 게임이 Steam 뉴스 피드를 가지므로 재발 빈도 높은 패턴 — 영구 게이트 효과 큼.
- cluster_report 재실행 시 steam 10건 후보 소멸 (live `recognize()` 억제). daily_deals.xml·news.xml 2건은
  path-template 달라 cluster 안 됨 (one-off, 안 건드림).
- 기존 config 12건 손 안 댐 (slug 마이그 X, Rule D 회피). recognizer 는 이후 등록부터.

### slug 중복 폴링 주의 (§8)
기존 10건 slug = `host_store-steampowe_feeds_<hash>` (fallback). recognizer 는 `_slug_board=appid` → slug
`host_store-steampowe_<appid>`. 같은 appid 재등록 시 new slug 로 중복 폴링 가능 — register.py canonical-url
중복 가드로 별도 봉합 필요(미구현 시 이 항목이 기록). 기존 폴링엔 영향 없음.

## 회귀 검증
```
$ PYTHONPATH=. python tests/recognizers/test_steam_news.py
  PASS board_extract / slug_board / roundtrip_members (app-feed 10 / 제외 2 · all ok) /
       recognize_integration / hub_url_normalizes_to_feed / other_host_neg / same_host_neg[5종] / no_reject_conflict
  12 passed

$ PYTHONPATH=. python scripts/probe_smoke.py --stage 3 --stage 5
  [stage 3] 83/83 OK   [stage 5] 0 FAIL · coverage 29/29
  ==== summary ==== PASS 621  FAIL 0  → exit 0

$ PYTHONPATH=. python scripts/cluster_report.py   # 봉합 확인
  recognized 40 · [A] store.steampowered.com cluster 소멸 (10건 흡수, daily_deals/news.xml 은 비-cluster)
```

## 비고
recognizer-extension 의 *multi-family cluster* 케이스 — 12건 중 10건만 한 family(app-feed)로 묶고 2건(전역 피드)
제외. 추가로 피드 URL 뿐 아니라 **사람-paste 허브 URL** 도 같은 config 로 정규화하는 2-패턴 설계.
github-releases(non-identical canonical) 와 같은 round-trip 모델, hoyolab(byte-identical) 과 대비.
SKILL §2(family 분리·변수 슬롯 판단)·§4(같은-host negative)·§8(slug 중복) 실증.
