---
slug: host_mobiusdigitalga_news_21205848
url: https://www.mobiusdigitalgames.com/news/
status: 🧩 수동 config — Weebly RSS feed 로 baseline 10건 등록
outcome: handcrafted
date: 2026-05-26
failure_keys: [posts_nonempty, first_article_archive, rss_feed_available]
config_strategy: httpx_html
---

## 무엇이 일어났나
preflight: miss — `configs/host_mobiusdigitalga_news_21205848.json` 없음, `recognize(url)` = `None`, 로컬 `.FAILED.json`/기존 probe artifact 없음. N100 접근 없이 로컬 `python scripts/probe.py "https://www.mobiusdigitalgames.com/news/" --lite` 로 재현했다.

probe digest 는 HTTP 200, 정적 HTML 충분, HTML 반복 후보 14건이었다. 문제는 첫 후보가 실제 글이 아니라 사이드바 archive 링크였다:

- `first_article_url=https://www.mobiusdigitalgames.com/news/archives/06-2025`
- `html[1] selector=p.blog-archive-list > a.blog-link`, `child_count=77`
- 실제 글 행은 `#wsite-content > div.blog-post`, `child_count=10`, sample URL `https://www.mobiusdigitalgames.com/news/patch-16-finishes-rolling-out-steam-gets-a-hotfix`

같은 page에서 validated RSS 후보도 있었다: `https://www.mobiusdigitalgames.com/1/feed`, `root_tag=rss`, `item_count=10`.

## 무엇을 바꿨나
`configs/host_mobiusdigitalga_news_21205848.json` 을 추가했다.

- 목록: `https://www.mobiusdigitalgames.com/1/feed`
- `row_selector: channel > item`
- `post_id`: `guid`/`link` 의 `/news/<slug>`
- `published_at`: RSS `pubDate` (`%a, %d %b %Y %H:%M:%S %z|%Z`)
- 본문: item link 페이지의 `div.blog-content`
- `polite_sleep`: robots.txt 에 `dotbot` crawl-delay 10이 있어 보수적으로 `10..10` 적용. `User-agent: *` 에 `/news/` disallow 는 없음.

## 회귀 검증
영향 사이트는 이 단일 config 1개다. engine/probe/prompt 변경 없음.

- `python scripts/register.py --config "configs/host_mobiusdigitalga_news_21205848.json"` → PASS, baseline 10건
- 직접 adapter 실행 → posts 3건 샘플, 첫 글 body_len 1866
- `python scripts/probe_smoke.py` → FAIL: stage 1/2 fixture artifact 부재 (`skku`, `trickcal`, `arca`, `mabinogi` diagnosis/digest 없음). 이번 config와 무관한 로컬 artifact 문제.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS, config validate/make_adapter 257/257 OK, heuristic units 1235 cases 0 FAIL

## 일반화 검토
일반화 가능한 신호는 있다. `list_candidates.json` 에서 archive sidebar가 실제 글 row보다 먼저 잡히는 유형이고, 기존 `forum.nexon.com_bluearchive_board_list_board_1018` 도 probe first_article이 메뉴/사이드바 링크를 글로 오인한 케이스다. `host_comic-days-com_info_ba9e6887` 도 archive URL과 실제 entry URL 불일치가 기록돼 있다.

다만 이번 chunk의 허용 변경 범위는 site config + case 기록으로 보았고, probe 후보 랭킹(C-layer) 수정은 allow-list 밖이다. 따라서 이번 작업에서는 generic probe heuristic을 넣지 않는다.

## escalate (allow-list 밖 일반화 후보)
archive/category/sidebar 링크가 반복 후보 상위에 오고, 같은 DOM 안에 더 낮은 순위의 article/blog post row가 존재하는 경우 `first_article_url` 랭킹을 보정하는 C-layer probe heuristic 후보가 있다. 다음 chunk에서 `probe/extract.py` 또는 후보 랭킹 로직 소유권을 명시해 별도 처리하는 것이 맞다.

