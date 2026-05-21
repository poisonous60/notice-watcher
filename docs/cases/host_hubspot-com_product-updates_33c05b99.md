---
slug: host_hubspot-com_product-updates_33c05b99
url: https://www.hubspot.com/product-updates
status: "🔧 수동 config — HubSpot Releases and Updates JSON API 로 baseline 30건 등록"
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, khoros_resources_api]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [hubspot, khoros, product-updates, json-api]
---

## 무엇이 일어났나

원 큐는 `rc=1 gen_fail` 로 들어왔고, 사용자 전달 실패 요지는 마지막 생성 config 가
`httpx_json` 의 `list_path: ["messages"]` 를 쓰면서도 posts 0건으로 검증 실패했다는 것이다.

로컬 worktree에는 처음에 `output/poll_state/host_hubspot-com_product-updates_33c05b99.FAILED.json` 와
probe 산출물이 없었다. `scripts/probe.py --lite` 를 재실행하자 timeout 전에 일부 산출물은 생성됐지만
`diagnosis.json` 까지는 쓰지 못했다. 생성된 `list_candidates.json` 은 정적 HTML 반복 후보가 nav/menu 위주이고
`first_article_url` 도 `/t5/News/ct-p/communityboard` 로 잡아, 실제 글 목록을 정적 selector 로 찾기 어렵다는
신호를 보였다.

대상 URL은 `https://community.hubspot.com/t5/Resources/ct-p/resources` 로 리다이렉트된다. 이 페이지의
`Releases and Updates` 탭은 JS에서 다음 Khoros custom endpoint를 호출한다.

`/plugins/custom/hubspot/hubspot/resources?posts_per_page=30&node_id=releases-updates&order_by=last_updated&labels=&page=1&catId=resources&node_type=board`

`node_id=resources&node_type=category` 는 category 전체/탭 상태에 따라 의도와 다른 결과가 될 수 있고,
`node_id=releases-updates&node_type=board` 가 product updates에 해당하는 목록 30건을 안정적으로 반환한다.

## 픽스

`configs/host_hubspot-com_product-updates_33c05b99.json` 을 `httpx_json` config 로 작성했다.

- 목록: HubSpot custom resources endpoint, `node_id=releases-updates`, `node_type=board`
- `post_id`: `messages[].id`
- `title/url/published_at/author/category/summary/cover_image`: `messages[]` 필드에서 추출
- 본문: 공개 Khoros API `https://community.hubspot.com/api/2.0/messages/{post_id}?fields=body,subject,view_href,post_time`
- `polite_sleep`: `community.hubspot.com/robots.txt` 의 `Crawl-delay: 5` 반영

## robots / polite_sleep

`https://community.hubspot.com/robots.txt` 는 200이고 `Crawl-delay: 5` 를 명시한다.
RSS path는 `Disallow: /mjmao93648/rss` 이지만 이번 config는 RSS가 아니라 페이지 JS가 쓰는 JSON endpoint와
public message API를 사용한다. config는 엔진 기본보다 느린 `polite_sleep` 5-7초를 둔다.

## 회귀 검증

- `python scripts/register.py --config configs/host_hubspot-com_product-updates_33c05b99.json`
  - baseline 30건 등록
  - 샘플: `1277188`, `1275695`, `1275467`
- `make_adapter` 스모크
  - `fetch_list(page_size=10)` 10건 반환
  - 첫 글 `fetch_article()` body length 6335

## 트랙 B 검토

- **2a (인식기) — 보류.** Khoros 플랫폼 신호는 있지만 HubSpot custom resources endpoint의 `node_id`/tab 매핑이
  사이트별 JS에 묶여 있어 이번 단건에서 범용 recognizer로 승격하지 않았다.
- **2b (`--article-url`) — X.** 첫 글 URL 교정만으로 해결되는 문제가 아니라 목록 endpoint 파라미터 문제다.
- **2c/2d (probe/prompt 개선) — 보류.** `posts_nonempty` 누적은 많지만 이번 root-cause는 HubSpot custom
  endpoint의 `node_type=board`/`node_id=releases-updates` 조합이다. 이 한 사례만으로 범용 Khoros 휴리스틱을
  넣으면 다른 Khoros community의 category/resource page를 잘못 가로챌 수 있다.
- **2e (수동 config) — O.** 단일 사이트 JSON API config 로 해결 가능하고, engine/probe/prompt 변경 없이 검증된다.

일반화 안 되는 이유: Khoros라는 플랫폼은 보이지만 HubSpot이 얹은 `/plugins/custom/hubspot/hubspot/resources`
controller와 tab id는 HubSpot 전용이다. 플랫폼 recognizer는 같은 구조의 추가 사례가 들어오면 별도 설계로 다룬다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 누적 49건, `httpx_json` 0건. 동일 root-cause는 `khoros_resources_api` 로 첫 기록.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: register baseline 30건, make_adapter list/body 확인.
5. **outcome=handcrafted**: HubSpot 전용 endpoint를 박은 단일 사이트 config이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_json` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 0건 사유**: 위 §트랙 B 검토 참조.
