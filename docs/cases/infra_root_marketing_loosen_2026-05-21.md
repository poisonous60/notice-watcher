---
slug: infra_root_marketing_loosen_2026-05-21
url: https://community.nodebb.org/
status: ✅ 게이트 완화 — root_marketing 이 same-host self-article 있는 board 를 오거부하던 것 차단
outcome: improved
date: 2026-05-21
fix_layer: C
failure_keys: [gate_reject_root_marketing]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [gate, root-marketing, board-shape, false-reject, batch-2026-05-21-forums, nodebb, xenforo, ips]
---

## 무엇이 일어났나

`catalog=2026-05-21-forums` batch (100 사이트) 의 rc=3 gate_reject 27건 중 **root_marketing_homepage
게이트가 14건을 거부 — 전부 진짜 포럼** (community.nodebb / community.amd / community.spotify /
forum.qt.io / forum.xda-developers / forums.freebsd / forums.macrumors / forums.nexusmods /
hardforum / linustechtips / quasarzone / rhymix / elevenforum / head-fi). XenForo/IPS/NodeBB/
Khoros/Rhymix 류 포럼 root 가 모두 false-reject.

### 진단 (§2 진입 강제 인용)

1. last_feedback (rc=3 게이트): `[register] root 도메인 마케팅 랜딩/허브 페이지 같음 … ❌ 등록 거부`
   `[신호: marketing_hits=2 total_same_host=4]` (nodebb)
2. diagnosis verdict (로컬 재-probe): `정적 HTTP로 충분` / 글 목록 후보 HTML 9건 + 첫 글 same-host
   `/topic/19312/...` + 본문 진입 OK
3. `docs/config 자동생성 실패 케이스.md` §"게이트 4: root 도메인 마케팅 랜딩" 매칭
4. 분기 **2c/2d** (probe digest 신호 게이트 consumer 완화), fix_layer C
5. 누적 cross-check: `cases_index query --signal "root_marketing|board_shape"` → 1건
   (`infra_root_marketing_homepage_gate_2026-05-19` = 이 게이트 신설). track_b_trigger 해당 X
   (이건 그 게이트의 *완화*). 동류 batch: discourse root-form (3b622b3)
6. preflight: `[infra change — batch 분석 기반, 단일 큐 slug 아님]`

## 근인

`probe/extract.py:root_marketing_homepage` 트리거 = path='/' + top7 selector 의 nav/carousel/
dropdown 키워드 ≥2 + `total_same_host ≤15`. docstring 가정 *"진짜 board root 는 same-host article
rows ≥30"* 이 **JS-렌더 포럼 root 에서 깨짐** — NodeBB/XenForo 의 토픽 리스트가 carousel/recent-card(JS)
라 정적 repeating-row 검출이 작게(4~8) 잡히고, nav/dropdown 이 top7 우세 → 세 조건 충족 → 거부.
실측(nodebb): `marketing_hits=2` 가 진짜 nav(`#main-nav`, `navigation-dropdown`)지만, **같은 digest 에
`first_article_url`=same-host `/topic/19312`, `slick-slide` 후보 sample_url 도 그 토픽 = 실제 board 행
존재.** 즉 same-host self-article 증거가 명백한데 거부 = false-positive.

## 무엇을 바꿨나 (단일 영구 게이트, fix_layer C)

`scripts/register.py:_root_marketing_homepage_check` — `is_root_marketing_homepage` 확인 후,
**`_board_shape_check(digest, url)` 가 통과시킬 페이지면 거부 안 함 (escape).** board_shape 는 same-host
self-article 신호(first_article same-host / 같은-host 반복행 / 목록 JSON·feed) 가 하나라도 있으면 통과 =
"확실히 게시판 아님" 의 권위 게이트. root_marketing 은 그 통과 기준을 *공유* → 두 게이트 drift 불가.
이제 root_marketing 은 board_shape-fail 의 marketing-구조 부분집합에만 발화(더 정확한 '카테고리/섹션 URL
권장' 메시지). **producer(`extract.py`)는 무수정 → `test_root_marketing_homepage.py` 무영향.**

사용자 결정 (2026-05-21): "게이트 거부는 확실히 게시판 아닌 것만 분류, 나머지 다 실행."

## 검증

- `register.py --gate-only "https://community.nodebb.org/"` → **모든 게이트 통과** (이전 rc=3 → rc=6).
- `probe_smoke.py --stage 3 --stage 5` → exit 0 (configs 93/93, heuristic 603 케이스 0 FAIL —
  producer 테스트 4 media root 매칭 그대로 통과).
- stage 1/2 의 skku/trickcal/arca/mabinogi FAIL = pre-existing stale fixture (hook 무관).

## outcome = improved

거부 *분류* 게이트의 false-positive 차단 = generic 추론(LLM 생성 경로)이 NodeBB/XenForo/IPS 류 board
root 를 dedicated adapter 없이 시도할 수 있게 됨. `recognize_reject`(거부 분류 개선=improved) 와 동류.
대조: discourse root-form(3b622b3)은 DiscourseAdapter dispatch = handcrafted. 이건 게이트 완화라 generic
경로를 열 뿐 platform-dispatch 아님 → improved.

주의: 이 변경은 게이트가 LLM 을 *막지 않게* 함. 14건이 실제로 등록되는지는 batch 재실행에서 검증(별도). row
없는 진짜 marketing root(예: 일부 Khoros 가 정적에 self-article 0)은 board_shape 가 여전히 거부 — 정상.

## 트랙 B 검토

- 본 변경 자체가 트랙 B (같은 패턴 14건 + 미래 포럼 root 자동 처리).
- deferred 후보 (다음 세션): row 가 정적 digest 에 *없는* 플랫폼(Khoros/Rhymix 일부) → generator-meta
  recognizer + 플랫폼 adapter (XenForo `/whats-new/posts`, IPS) — discourse 동형. `docs/cases/_deferred_heuristics.md`.
