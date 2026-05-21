---
slug: host_call-for-papers_root_90032f22
url: https://call-for-papers.sas.upenn.edu/
status: 🧩 수동 config — root landing 을 all recent posts 목록으로 remap
outcome: handcrafted
date: 2026-05-22
failure_keys: [posts_nonempty, wrong_first_article, nav_only_candidates, empty_rss]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, drupal, cfp, remap, nav-candidates]
requested_by: batch
---

## 무엇이 일어났나

batch `gen_fail(rc=1)` 로 들어온 케이스다. 제출 URL `https://call-for-papers.sas.upenn.edu/` 는
Drupal landing page 이며, 본문에는 안내문과 카테고리 navigation 이 있다. root 자체에는 post row 가
없어 자동 생성이 카테고리 nav 의 첫 링크인 `/category/african-american` 을 첫 글 후보로 잡았다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`
- `[warn] matches_probe_first_article: probe first_article_url='https://call-for-papers.sas.upenn.edu/category/african-american' 와 일치하는 글 URL 없음`
- `[warn] count_ballpark: 0건 (probe 후보 child_count≈40)`

`diagnosis.json` 은 `정적 HTTP로 충분` 으로 봤고, JSON API 후보는 없었다. `feed_candidates.json` 에
`/rss.xml` 이 있었지만 직접 확인 결과 channel metadata 만 있고 item 이 없는 빈 RSS 라 polling source 로
쓸 수 없었다.

## 픽스

`register.py --reuse-probe "https://call-for-papers.sas.upenn.edu/"` 는 실패 이후 probe/engine 계열
커밋 덕분에 config 생성을 성공시켰다. 다만 자동 결과가 `/category/african-american` 단일 카테고리로
좁혀져 root 구독 의미와 맞지 않았다.

`configs/host_call-for-papers_root_90032f22.json` 은 같은 Drupal row selector 를 유지하되 board 를
`all` 로 바꿔 `/category/all` 을 polling 한다. 이 사이트의 카테고리 메뉴 첫 항목도 `all recent posts`
이며, 실제 최신 CFP 항목 30건을 제공한다. submitted root URL 은 `_source_url` 로 보존했다.

robots.txt 는 `Crawl-delay: 60` 을 포함하고, config 의 `polite_sleep.min=60` 으로 반영했다.

## Track B 검토

- **2a 인식기 — X.** Drupal CFP 단일 사이트의 root-to-category remap 이며, 플랫폼 recognizer 로
  일반화하기에는 host 특화 규칙이다.
- **2b article-url — X.** article URL 하나를 고치는 문제가 아니라 root landing 에 post row 가 없는
  목록 source 선택 문제다.
- **2c/2d probe/prompt/engine — 보류.** nav-only gate 는 이 케이스를 거부하려 했지만 LLM 분류기가
  category 반복 링크를 근거로 board 라고 veto 했다. generic screen-out/recognizer Track B 는 별도
  same-tree 작업과 충돌 위험이 있어 이번 지시의 allow-list 밖 파일은 건드리지 않았다.
- **2e 수동 config — O.** 기존 `httpx_html` 로 `/category/all` 을 수집하면 안정적으로 해결된다.

일반화 안 되는 이유: root landing 이 실제 all-posts URL 을 sidebar nav 에만 노출하는 host 특화 구조라,
이번 작업에서는 generic 추론 개선 없이 단일 config remap 으로 제한했다.

## 회귀 검증

- `preflight: b-hit — host_call-for-papers_root_90032f22`
  - 기존 config/recognizer 없음.
  - FAILED 이후 영향 영역 커밋 존재.
  - `python scripts/register.py --reuse-probe "https://call-for-papers.sas.upenn.edu/"` → PASS, baseline 30건.
- URL/remap 확인
  - `/rss.xml` → 200, `application/rss+xml`, item 0건.
  - `/category/all` → 200, `article.node-cfp` rows.
- `python scripts/register.py --config configs/host_call-for-papers_root_90032f22.json`
  - PASS, baseline 30건.
  - first posts: `105260`, `105259`, `105256`.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `posts_nonempty` 계열 누적은 많지만 이번 지시는 Track B shared 파일 수정을 금지했다.
3. **누구 깰까**: 새 config 파일 1개와 해당 poll state 만 영향. 기존 config 영향 0.
4. **검증**: register `--reuse-probe` 성공, remap 확인, register `--config` baseline 30건.
5. **outcome=handcrafted**: 자동 config 를 그대로 쓰지 않고 root 의미 보존을 위해 list URL board 를 손으로 골랐다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` selector 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §Track B 검토 참조.
