---
slug: host_indiehackers-co_root_e4490db0
url: https://www.indiehackers.com/
status: "🔧 손 config 추가 — 정적 Ember HTML의 story 카드에서 홈 피드 30건 baseline"
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, first_article_url_missing, static_variant_rows_not_promoted]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [indiehackers, ember, homepage-feed, body-empty-acceptable, deferred-heuristic]
---

## 무엇이 일어났나
자동 생성은 세 번 모두 `[FAIL] posts_nonempty: 0건` 으로 실패했다. `list_candidates.json` 에는 반복 후보가 `head/script/meta/link` 뿐이고 `first_article_url=null` 이라 LLM 이 `playwright_html` selector 를 여러 번 바꿔도 실제 row 를 잡지 못했다.

artifact 를 다시 보니 `s1.H4.html` 에는 이미 홈 피드가 정적으로 들어 있었다. 예: `div.story.homepage-post` 아래 `a.story__text-link[href]`, `h3.story__title`, `p.story__summary` 구조가 반복된다. probe digest 가 이 S1 variant 의 row 를 `list_candidates.json` 으로 승격하지 못한 것이 자동 실패의 핵심이다.

## 처리
`configs/host_indiehackers-co_root_e4490db0.json` 를 손작성했다.

- `strategy=httpx_html`
- `row_selector: div.story.homepage-post`
- `row_required_selector: a.story__text-link[href]`
- `post_id`: `/post/.../<slug>` 또는 `/product/...?...post=<id>` 에서 안정 토큰 추출
- `url`: story link 를 `urljoin` 후 query/fragment 제거
- `summary`: 있으면 `p.story__summary`
- `article.body_empty_acceptable=true` + `content=[]`

본문까지 안정적으로 긁는 공개 API/HAR 근거는 artifact 에 없었다. 홈 피드 새 글 알림 목적이므로 제목/URL 중심 config 로 제한했다.

## 트랙 B
- 2a 인식기: X. Indie Hackers 단일 사이트 특수 구조다.
- 2b `--article-url`: X. click artifact 는 글 URL을 얻지만 목록 row 추출 실패를 고치지 못한다.
- 2c probe 휴리스틱: O, deferred. `s1.H4.html` 처럼 probe 의 진입 variant 중 하나에는 row 가 있는데 최종 `list_candidates.json` 에 승격되지 않는 패턴이다. allow-list 밖 `probe/` 변경은 금지되어 `_deferred_heuristics.md` 에 후보만 남겼다.
- 2d probe 오작동: O, deferred와 동일. HAR 파일은 artifact 디렉터리에 없고 summary 에만 `traffic.har` 언급이 남았다.

일반화 안 하는 이유: S1 variant 중 어떤 것을 list 후보 소스로 삼을지 바꾸는 것은 `probe/extract.py` 또는 digest wiring 변경이 필요하다. 이번 hard-stop allow-list 에서는 단건 config가 안전한 해결이다.

## 검증
- `python scripts/register.py --reuse-probe "https://www.indiehackers.com/"` → exit 1, 여전히 `[FAIL] posts_nonempty: 0건`.
- `python scripts/register.py --config configs/host_indiehackers-co_root_e4490db0.json` → exit 0, baseline 30건.
- 회귀 영향: config-only 추가, engine/probe/prompt 변경 없음.

