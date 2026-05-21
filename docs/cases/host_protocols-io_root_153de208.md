---
slug: host_protocols-io_root_153de208
url: https://www.protocols.io/
status: 🔧 손 config 등록 후보 — public protocol search 목록 playwright_html 10건 검증
outcome: handcrafted
date: 2026-05-21
failure_keys: [spa_render_required, root_landing_page, carousel_duplicates]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, protocols-io, spa, playwright-html]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

root 페이지에는 공개 protocol 카드가 보이지만 `#featured-protocols` carousel 이 같은 7개 항목을 반복 복제한다.
그 selector 를 그대로 쓰면 post_id 중복으로 새 글 감지에 부적합하다. 대신 같은 포털의 public protocol list인
`https://www.protocols.io/search` 에서 `article._1cqv171` rows 를 확인했다.

## 픽스

`configs/host_protocols-io_root_153de208.json` 생성. `_source_url` 은 root 로 보존하고 list URL은 public search
목록으로 둔다. `post_id` 는 `/view/<slug>` 에서 추출하고, 제목/날짜/작성자/type 을 row에서 추출한다.

## Track B 검토

- **2a 인식기 — X.** protocols.io 단일 포털 보정이며 새 플랫폼 인식기는 allow-list 밖이다.
- **2b article-url — X.** 첫 글 오인이 아니라 root carousel 중복 문제다.
- **2c/2d probe/generate — 보류.** carousel duplicate de-dupe 는 engine/probe 변경이 필요해 hard-stop 대상이다.
- **2e 수동 config — O.** public search route 는 안정적인 list rows 를 제공한다.

일반화 안 되는 이유: root carousel duplicate 제거는 selector 만으로 안전하게 표현하기 어렵고, de-dupe 로직은 엔진 변경이다.

## 회귀 검증

- `preflight: miss — host_protocols-io_root_153de208` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- live adapter smoke → list 10건, first post `protocol-of-a-systematic-review-with-meta-analysis-d6tq9emw`, article body 225346자.
