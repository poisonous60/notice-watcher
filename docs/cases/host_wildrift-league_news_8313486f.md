---
slug: host_wildrift-league_news_8313486f
url: https://wildrift.leagueoflegends.com/news/
status: "✅ 수동 config (Riot Next.js data-testid cards)"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [posts_nonempty, schema_invalid_source]
config_strategy: httpx_html
engine_files_touched: []
adapters_changed: []
tags: [riot, next-js, gacha-global]
requested_by: user
---

# Wild Rift news — Riot Next.js card grid

## 요약

자동 생성 config 는 styled-components class chain 을 row selector 로 잡아 build churn 에 취약했고, 동시에 `source: text` 같은 스키마 밖 source 를 만들어 `make_adapter ConfigError: invalid field source 'text'` 로 실패했다. live `https://wildrift.leagueoflegends.com/ko-kr/news/` HTML 은 정적 응답 안에 Riot 공통 Next.js 카드 DOM 을 싣고 있어서 TFT canonical config 와 같은 `data-testid` 기반 `httpx_html` config 로 처리했다.

## DOM evidence

Live HTTP check on 2026-05-28:

```text
status 200 https://wildrift.leagueoflegends.com/ko-kr/news/
section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"][href^="/ko-kr/news/"] => 10 rows
first row: /ko-kr/news/game-updates/wild-rift-patch-notes-7-1f
title: 와일드 리프트 7.1f 패치 노트
datetime: 2026-05-27T09:00:00.000Z
```

Stable attributes observed on the list page:

```text
data-testid="article-card-grid"
data-testid="articlefeaturedcard-component"
data-testid="card-title"
data-testid="card-date"
data-testid="card-description"
data-testid="card-image"
```

The failed selector was a generated class path:

```text
div.sc-4d29e6fd-0.hzTXxn > a.sc-d924ada1-0.hrwDHj.sc-d043b2-0.bZMlAb.sc-8e176a18-5.hwacGe.action
```

That is the wrong durability boundary for Riot's styled-components build output.

## Reference

TFT canonical config from the same batch uses the same Riot Next.js platform shape:

```text
strategy: httpx_html
url_template: https://teamfighttactics.leagueoflegends.com/ko-kr/news/
row_selector: section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"][href^="/ko-kr/news/"]
row_required_selector: time
post_id: :self href + regex_extract /ko-kr/news/(?:[^/]+/)*([^/?#]+)/?$
title: div[data-testid="card-title"]
url: :self href + urljoin host base
published_at: time@datetime + iso8601
author: const Riot Games
```

Wild Rift only changes host-specific values (`site`, `url_template`, `Referer`, and `urljoin` base).

## Track B 6-layer audit

- **E** schema 거부: hit for the original failure signature — `source: text` is already rejected by `engine/config_schema.py`, which is why the bad generated config failed early. No schema change needed.
- **D** retry feedback: miss — the feedback already exposed both `invalid field source 'text'` and `fetch_list 0 posts`; the agentic loop still anchored on brittle generated classes.
- **C** probe digest 신호: hit candidate — probe/list artifact already had stable `data-testid` evidence, but the first-article picker drifted to nav/menu content (`/ko-kr/game-overview/`) before the row selector was stabilized. This belongs in a future Riot platform recognizer/probe signal, not this single config patch.
- **B** few-shot: miss — TFT is already the canonical near-example; this Wild Rift config is a host-specific application of that pattern, not a new few-shot.
- **A** system rule: miss — adding a broad prompt rule for all styled-components sites would be too noisy; the safer rule is platform-specific: prefer Riot `data-testid` cards on Riot Next.js news pages.
- **F** engine/recognizer coverage: hit candidate, deferred — a Riot Next.js platform recognizer could emit this config for `*.leagueoflegends.com` news pages. Current batch evidence has TFT(done) + Wild Rift(handcrafted) = 2 live sites, while four related Riot-ish endpoints were gate/url rejects, so the recognizer is recorded as deferred instead of added now.

## Ship evidence

User request for this slug in the handoff brief:

```text
Task: wildrift.leagueoflegends.com/news/ ? Riot Next.js news config
Goal: configs/host_wildrift-league_news_8313486f.json ... Riot endpoint teamfighttactics.leagueoflegends.com/news/ ... platform ...
```

This is an explicit per-site ship request after batch `2026-05-28-games-gacha-global-05` left Wild Rift as `gen_fail`.

## Fix

`configs/host_wildrift-league_news_8313486f.json`:

- `strategy: httpx_html`
- `url_template: https://wildrift.leagueoflegends.com/ko-kr/news/`
- `row_selector: section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"][href^="/ko-kr/news/"]`
- `post_id` from the row href with `/ko-kr/news/(?:[^/]+/)*([^/?#]+)/?$`
- `published_at` from `time@datetime`
- `article.content` from `main`

## 회귀 검증

```text
schema OK
list 10
  wild-rift-patch-notes-7-1f '와일드 리프트 7.1f 패치 노트' 2026-05-27T09:00:00+00:00
  wild-rift-patch-notes-7-1e '와일드 리프트 7.1e 패치 노트' 2026-05-13T09:00:00+00:00
  smash-2026-location-reveal '2026 와일드 라운드: 스매쉬 개최지 공개' 2026-05-06T17:00:00+00:00
body chars 42969
register.py --config: baseline 10, rc=0
probe_smoke.py --stage 3 --stage 5: PASS 1743, FAIL 0, WARN 1, rc=0
```

The WARN is the existing `test_worker_failure_routing` protocol warning (`run() 함수 없음 — protocol 미준수`), not a failure in this config.

## 일반화 후보

Riot Next.js platform recognizer candidate: if host is `*.leagueoflegends.com` or another Riot news host and the list DOM contains `section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"]`, generate the TFT/Wild Rift-style config with host-local `url_template`, `Referer`, and `urljoin` base. Deferred until the cluster has broader positive evidence.
