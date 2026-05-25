---
slug: _sports_hub_vs_board_criterion_2026-05-25
status: investigation
date: 2026-05-25
tags: [criterion-design, het-hub-gate, sports-batch]
---

# sports hub vs board 판정 기준 조사

## 범위

코드 변경 없이 N100 probe artifact 를 read-only 로 확인했다. 로컬 worktree 에는 `output/` 이 없었고,
`python scripts/triage.py list` 는 "처리할 실패 등록 없음"을 출력했다. 따라서 anchor 3건과 sports batch 표본은
`$DEPLOY_HOST:~/notice-watcher/output/probe/<slug>/list_candidates.json` 및 poll_state marker 를 읽어서 정리했다.

## 3 anchor cluster 요약

### espn.com/soccer/ (hub reject 기대)

| cluster | cc | shape | path / pattern |
|---|---:|---|---|
| `ul.editions > li` | 24 | nav | `/` |
| `ul > li.sub` | 22 | nav | `/nba/` |
| `ul > li` | 17 | nav | `/fantasy/` |
| `ul > li.team` | 14 | nav/team | `/soccer/team/_/id/{n}/arsenal` |
| `ul.split > li.team` | 14 | nav/team | `/soccer/team/_/id/{n}/arsenal` |
| `ul.headlineStack__list > li` | 9 | article | `/soccer/story/_/id/{n}/...` |
| `ul.quicklinks_list > li.quicklinks_list__item` | 8 | nav/quicklink | `fantasy.espn.com/games/...` |
| `section.col-one > article.sub-module.quicklinks` | 6 | nav/quicklink | `/watch/catalog/...` |

핵심: article-shape cluster 는 존재하지만 `cc=9` 1종뿐이고, nav/team/watch cluster 가 `cc=24/22/17/14/14`로 우세하다.
현재 `has_article_cluster(cc>=5)` 기준만으로는 이 hub 를 통과시킨다.

### cbssports.com/nba/ (hub reject 기대)

| cluster | cc | shape | path / pattern |
|---|---:|---|---|
| `ul.EightPack-list > li.EightPack-item` | 40 | video/hub | `/watch/live` |
| global nav category item | 28 | nav | `/nfl/scoreboard/` |
| category menu item | 20 | nav | `/college-basketball/` |
| dots nav item | 20 | nav | `/nba/` |
| subnav dots item | 19 | nav | `/nba/scoreboard/` |

핵심: clean article cluster 0종이다. 기존 기준으로도 reject 된다.

### biathlonworld.com/news (board OK 기대)

| cluster | cc | shape | path / pattern |
|---|---:|---|---|
| news category filter | 13 | same-page filter | `/news` |
| wide story list item | 10 | article | `/news/biathletes-who-rewrote-history/8TS3tSgirGsIbmouG005R` |
| narrow story list item | 10 | article | `/news/biathletes-who-rewrote-history/8TS3tSgirGsIbmouG005R` |
| sticky nav item | 5 | nav | `/calendar` |
| story category filter | 5 | same-page filter | `/news` |
| footer link | 5 | nav/footer | `/calendar` |

핵심: article cluster 2종이 같은 `/news/...` 구조로 반복된다. `/news` filter cluster 는 현재 board path 자체라
경쟁 nav 로 세면 안 된다. 경쟁 nav max 는 `cc=5`, article max 는 `cc=10`.

## 후보 기준 비교

### 후보 1: clean article dominance

정의:
- `clean_article_cluster`: same-host, `cc>=5`, path 가 slug/ID/placeholder 를 가진 글 상세 형태이며 selector/text 가
  nav/menu/footer/team/filter/quicklinks/dropdown/social/cookie 계열이 아닌 cluster.
- `competing_nav_cluster`: same-host, `cc>=5`, nav/menu/footer/team/league/score/watch/dropdown/quicklinks 계열 cluster.
  단 현재 board path 자체(`/news`, `/nba/news` 등)의 filter/tab cluster 는 제외한다.

판정:
- `clean_article_count == 0` 이면 reject.
- `clean_article_count == 1` 이고 `article_max_cc / competing_nav_max_cc < 1.0` 이면 reject.
- `clean_article_count >= 2` 이고 clean article prefix 가 같은 board path 아래면 OK.

anchor 결과:

| site | article_max | nav_max | count | 판정 |
|---|---:|---:|---:|---|
| ESPN soccer | 9 | 24 | 1 | REJECT |
| CBS NBA | 0 | 40 | 0 | REJECT |
| Biathlon news | 10 | 5 | 2 | OK |

이 기준이 가장 직접적이다. ESPN 처럼 "작은 headline stack 하나 + 거대한 nav/team hub" 인 케이스를 막고,
Biathlon 처럼 responsive wide/narrow story list 가 2종으로 잡히는 board 는 살린다.

### 후보 2: article prefix coherence

정의:
- clean article cluster 의 normalized prefix 가 현재 board path 계열에 모이는지 본다.
- quicklinks/watch/games/footer/nav selector 는 prefix 계산에서 제외한다.

관찰:
- ESPN soccer: clean article prefix 는 `/soccer/story` 1종이지만, 주변 same-page content 후보가 `/watch/catalog`,
  `fantasy.espn.com/games`, team/league nav 로 강하게 섞인다. prefix coherence 만으로는 reject 근거가 약하다.
- Biathlon: clean article prefix 가 `/news/<slug>/<id>`로 고정된다.

결론: 보조 신호로만 적합하다. 단독 threshold 로 쓰면 ESPN soccer 를 놓친다.

### 후보 3: nav dominance without article rows

현재 `_heterogeneous_hub_check` 는 "글-링크 모양 cluster cc>=5 가 있으면 OK" 이다. 이 기준은 CBS 는 잡지만
ESPN soccer 를 놓친다. 기존 boolean 을 `clean_article_count`, `article_max_cc`, `competing_nav_max_cc`,
`prefix_coherent` 로 바꾸는 쪽이 낫다.

## sports batch 표본

| slug | 현재 marker | 관찰 | 기준 적용 예상 |
|---|---|---|---|
| `host_transfermarkt-c_aktuell_29abde15` | marker 없음 | article 0, nav/footer/link max 7 | REJECT |
| `host_uefa-com_insideuefa_7fe174ff` | REJECTED | article 0, in-page nav max 5 | REJECT |
| `host_mlssoccer-com_news_dec514dd` | marker 없음 | footer/about/topic nav 가 article-shape 로 오탐될 수 있음; clean article 0에 가까움 | REJECT 또는 추가 probe 필요 |
| `host_fis-ski-com_news_d42eb04e` | marker 없음 | cookie/header/nav only, article 0 | REJECT or render 필요 |
| `host_indycar-com_News_e4c69ade` | FAILED | `/news/{year}/...` article clusters 4종 `cc=10`, nav max 7 | OK; gen_fail 원인은 selector/validation 쪽 |
| `host_fifa-com_en_17a739e0` | REJECTED | top menu only, article 0 | REJECT |
| `host_si-com_nba_5b4f9f05` | marker 없음 | article clusters 2종 `cc=10/9`, nav team cluster `cc=31` | OK if count>=2+same-prefix escape 적용 |
| `host_espn-com_nba_267b7a1f` | registered | weak article clusters under `/nba/story`, very strong nav | false-reject 위험 fixture |
| `host_nba-com_news_701f6d5e` | registered | article clusters under `/news/...`; nav also strong | OK if count>=2+same-prefix escape 적용 |
| `host_nfl-com_news_3041485b` | registered | article cluster `cc=6`, competing nav 0 in filtered set | OK |

표본에서 보이는 위험은 `SI`, `NBA.com`, `ESPN NBA` 처럼 nav/team 메뉴가 큰 genuine sports news page 이다.
그래서 ratio 하나만 hard gate 로 쓰면 false-reject 가 난다. `count>=2 + same-prefix` escape 가 필요하다.

## 권장 기준

1. **권장안**: `_heterogeneous_hub_check` 의 `has_article_cluster` boolean 을 `clean_article_dominance` 로 교체한다.
2. **threshold**:
   - reject: `clean_article_count == 0`
   - reject: `clean_article_count == 1 AND competing_nav_max_cc >= clean_article_max_cc`
   - OK: `clean_article_count >= 2 AND clean_article_prefix_count == 1`
   - OK: `competing_nav_max_cc == 0`
3. **적용 위치**: `scripts/register.py:_heterogeneous_hub_check`. 현재처럼 gen_fail post-mortem 용으로 유지하고,
   pre-LLM hard gate 로 올리지는 않는다.

## false-reject 위험

- **ESPN NBA**: registered 표본인데 nav cluster 가 매우 크다. `ul.first-group > li.sub.pre-loadSubNav` 처럼 nav selector 가
  article URL 을 품는 경우를 clean article 로 세면 안 된다. 반대로 headline/news-feed article cluster 2종은 살려야 한다.
- **SI NBA**: team nav max `cc=31` 이 article max `cc=10` 보다 크다. ratio-only 기준이면 reject 되므로
  `clean_article_count>=2 + same-prefix` escape 가 필요하다.
- **NBA.com news**: drawer/nav 의 `/draft/{n}` 이 article-shape 로 보인다. selector keyword 필터로 nav article 오탐을 빼야 한다.
- **render 필요 site**: FIS Ski 처럼 정적 artifact 에 cookie/header/nav 만 잡히는 경우는 진짜 hub 와 SPA/render 필요를 구분하기 어렵다.
  이 기준은 "gen_fail post-mortem hint" 로 두고, render track 필요 여부는 별도 신호와 함께 판단해야 한다.

## 후속 chunk 제안

- `scripts/register.py:_heterogeneous_hub_check` 에 clean article/nav scorer 를 추가한다.
- fixture 는 최소 ESPN soccer(REJECT), CBS NBA(REJECT), Biathlon news(OK), IndyCar(OK), SI NBA(OK), NBA.com news(OK)를 둔다.
- 기대 효과: sports hub root 의 gen_fail 누수를 줄이되, genuine sports news page 는 `count>=2+same-prefix` escape 로 살린다.
