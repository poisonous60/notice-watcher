---
slug: host_circleci-com_changelog_5a868561
url: https://circleci.com/changelog/
status: 🧩 수동 config — CircleCI changelog RSS feed 로 baseline 30건 등록
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, row_selector_too_narrow, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [circleci, changelog, rss, selector-scope]
---

## 무엇이 일어났나

원 큐는 `rc=1 gen_fail` 로 들어왔고, 사용자 전달 실패 요지는 마지막 생성 config 가
`div.entry-title a.type-h3` 쪽 selector 에 묶이면서 `posts_nonempty` 검증을 통과하지 못한 것이다.

로컬 worktree에는 `output/poll_state/host_circleci-com_changelog_5a868561.FAILED.json` 와
`output/probe/host_circleci-com_changelog_5a868561/` 가 없어서 `triage.py show` 기반 진단은 재현할 수
없었다. 대신 dev box 에서 대상 URL을 직접 확인했다.

- `https://circleci.com/changelog/` 정적 GET: 200, HTML 약 583KB.
- `div.entry-title a.type-h3`: 현재 50개 존재하지만, 이 anchor 자체는 반복 row 가 아니라 title link 이다.
- 실제 HTML row 는 `div.entry.group.relative.flex` 이고, 각 row 안에 date/title/category/summary 가 있다.
- 더 안정적인 `https://circleci.com/changelog.rss` 가 200으로 열리고 `item/title/link/guid/pubDate/description`
  을 제공한다.

## 픽스

`configs/host_circleci-com_changelog_5a868561.json` 을 RSS 기반 `httpx_html` config 로 작성했다.

- 목록: `https://circleci.com/changelog.rss`, `row_selector: item`
- `post_id`: RSS `guid` 의 `/changelog/<slug>/`
- `title/url/published_at/summary`: RSS `title/link/pubDate/description`
- 본문: 개별 changelog page 의 `div.entry-content`

RSS feed 가 이미 full description 과 canonical URL/date 를 제공하므로 HTML timeline selector 보다 깨질 면이
작다. 본문은 실제 article page 에서 fetch 해서 `body_empty_at_baseline=false` 로 등록된다.

## robots / polite_sleep

`https://circleci.com/robots.txt` 는 200이고 `Crawl-Delay` 는 없다. `/changelog/` 와 `/changelog.rss` 는
`Disallow` 대상이 아니다. config 는 엔진 기본보다 좁히지 않고 보수적으로 `polite_sleep` 5-6초를 둔다.

## 회귀 검증

- `python scripts/register.py --config configs/host_circleci-com_changelog_5a868561.json`
  - baseline 30건 등록
  - `.FAILED.json` 없음
  - 샘플: `runner-release-3-1-9`, `xcode-26-5-available`, `ubuntu-22-04-24-04-and-26-04-machine-images-promoted-to-current`
- `make_adapter` 스모크
  - `fetch_list()` 10건 반환
  - 첫 글 `fetch_article()` body length 974

## 트랙 B 검토

- **2a (인식기) — X.** CircleCI 전용 changelog feed 이고 범용 플랫폼으로 보기 어렵다.
- **2b (`--article-url`) — X.** 첫 글 URL 교정 문제가 아니라 목록 row scope 및 RSS 선택 문제다.
- **2c/2d (probe/prompt 개선) — 보류.** `posts_nonempty`/`title_nonempty` 누적은 많지만 이번 직접 원인은
  사이트가 제공하는 RSS 를 선택하지 않은 것이다. RSS feed 우선 일반화는 다른 HTML board 를 feed-only 로
  바꾸는 부작용이 있어 별도 설계가 필요하다.
- **2e (수동 config) — O.** 단일 사이트의 안정 feed 로 해결 가능하고, engine/probe/prompt 변경 없이 검증된다.

일반화 안 되는 이유: `/changelog.rss` 는 CircleCI 사이트 고유 feed 이며, RSS 우선 정책을 자동화하면
HTML board 가 필요한 사이트까지 feed summary 로 축소할 수 있다. 이번 변경은 단일 config 로 제한한다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 43건, `title_nonempty` 5건. 동일 root-cause 는 `rss_feed_available`
   로 처음 기록.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: register baseline 30건, make_adapter list/body 확인.
5. **outcome=handcrafted**: 단일 사이트 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` XML parsing 사용이라 별도 fixture 추가 없음.
7. **트랙 B 0건 사유**: 위 §트랙 B 검토 참조.
