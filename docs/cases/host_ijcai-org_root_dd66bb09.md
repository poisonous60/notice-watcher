---
slug: host_ijcai-org_root_dd66bb09
url: https://ijcai.org/
status: "🧩 수동 config — root homepage 본문 공지 링크 4건 등록"
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [post_id_unique, nav_only_candidates, empty_rss, homepage_body_links]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, drupal, homepage, nav-candidates]
---

## 무엇이 일어났나

batch `gen_fail(rc=1)` 로 들어온 케이스다. 제출 URL `https://ijcai.org/` 는 Drupal root
homepage 이며 dedicated board URL 은 아니다. 자동 생성은 nav/menu 를 목록으로 오인했다.

`last_feedback`:

- `[FAIL] post_id_unique: 중복 4건`
- 직전 config 는 `nav#main-menu ul.menu > li` 를 row 로 잡아 `Future Conferences`,
  `Past Conferences`, `Proceedings` 같은 메뉴 항목을 글로 추출했다.
- 이전 시도도 `div.field-item.even > p` 또는 nav selector 로 흔들렸다.

probe 신호:

- `diagnosis.json`: `정적 HTTP로 충분`
- `nav_only_same_host`: `total_same_host=1`, `in_nav=1`, `outside_nav=0`
- `feed_candidates.json`: `https://ijcai.org/rss.xml` 발견
- 직접 확인한 `/rss.xml`: 200 `application/rss+xml`, item 0건

## 픽스

`configs/host_ijcai-org_root_dd66bb09.json` 을 수동 작성했다.

`list.url_template` 은 제출 URL 그대로 `https://ijcai.org/` 를 유지했다. RSS 는 비어 있어
사용하지 않았고, nav/menu 도 제외했다. 대신 root homepage 본문 중 공지성 링크가 모여 있는
5번째 문단만 polling source 로 좁혔다:

`div.field-item.even[property='content:encoded'] > p:nth-of-type(5) > a[href]`

현재 baseline 은 다음 4건이다.

- `Call for Nominations: IJCAI-2026 Awards`
- `AI Hub launched`
- `Funding Opportunities for Promoting AI Research`
- `Free Access to the AI journal`

robots.txt 는 `Crawl-delay: 10` 을 포함하고, config 의 `polite_sleep.min=10` 으로 반영했다.

## Track B 검토

- **2a 인식기 — X.** Drupal root homepage 단일 구조이며, 안정적인 platform recognizer 로
  일반화할 URL 규칙이 없다.
- **2b article-url — X.** 첫 글 URL 하나를 고치는 문제가 아니라 nav/menu 오인 문제다.
- **2c/2d probe/prompt/engine — 보류.** nav-only gate 는 이 케이스를 잡았지만 분류기 veto 가
  빈 RSS 후보와 homepage 허브성을 근거로 거부를 취소했다. 이번 위임 범위는 single slug config/case
  이며 shared code 변경은 같은 트리 작업과 충돌 위험이 있어 건드리지 않았다.
- **2e 수동 config — O.** root URL 안의 실제 사용자 가치를 가지는 본문 공지 링크만 좁히는 방식이
  가장 작은 변경이다.

일반화 안 되는 이유: dedicated list page 나 non-empty feed 가 없고, root homepage 의 특정 본문
문단만 공지 링크처럼 쓰이는 host 특화 구조다.

## 회귀 검증

- `preflight: b-hit — host_ijcai-org_root_dd66bb09`
  - 기존 `configs/<slug>.json`/recognizer 없음.
  - FAILED 이후 영향 영역 commit 존재.
  - `python scripts/register.py --reuse-probe "https://ijcai.org/"` 는 PASS 했지만 nav/menu 15건을
    baseline 으로 잡아 오탐으로 폐기했다.
- URL/remap 확인
  - `list.url_template` 은 제출 URL `https://ijcai.org/` 그대로 유지.
  - `/rss.xml` 은 item 0건이라 polling source 로 쓰지 않음.
- `python -c "import json; from engine.config_schema import validate_config; ..."` → `schema ok`
- `python scripts/register.py --config configs/host_ijcai-org_root_dd66bb09.json`
  - PASS, baseline 4건.
  - `body_empty_at_baseline=false`.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `nav_only_candidates`/`empty_rss` 유사 케이스는 있으나 이번 지시는 Track B
   shared 파일 수정을 금지했다.
3. **누구 깰까**: 새 config 파일 1개와 해당 poll state 만 영향. 기존 config 영향 0.
4. **검증**: schema 검증과 `register.py --config` 성공.
5. **outcome=handcrafted**: selector 와 polling source 를 손으로 골랐다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` selector 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §Track B 검토 참조.
