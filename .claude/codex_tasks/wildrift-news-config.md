# Task: wildrift.leagueoflegends.com/news/ — Riot Next.js news config

## Goal
`configs/host_wildrift-league_news_8313486f.json` 작성해 정적 HTML strategy 로 등록. 같은 batch (`2026-05-28-games-gacha-global-05`) 의 동료 Riot endpoint **teamfighttactics.leagueoflegends.com/news/** 가 이미 done 등록됐다 — 같은 platform 패턴 그대로 적용.

## Context — batch teammates (cross-site signal)
- `teamfighttactics.leagueoflegends.com/news/` → **done (registered)**. 시맨틱 `data-testid` 셀렉터 사용. canonical reference.
- `legendsofruneterra.com/news/`, `playruneterra.com/news/`, `wildriftforums.leagueoflegends.com/news/`, `marvelrivals.com/news/` 등 → rejected (gate_reject/url_dead). 작업 대상 아님.
- **wildrift (이 task)** → 유일한 gen_fail (rc=1).

## FAILED.json 핵심
- URL: https://wildrift.leagueoflegends.com/news/
- 마지막 시도 selector: `div.sc-4d29e6fd-0.hzTXxn > a.sc-d924ada1-0.hrwDHj.sc-d043b2-0.bZMlAb.sc-8e176a18-5.hwacGe.action` (styled-components 해시 — brittle, build 마다 변함)
- last_feedback: `make_adapter ConfigError: invalid field source 'text'` + `fetch_list 0 posts; posts_nonempty failed`
- probe 가 첫 글로 `https://wildrift.leagueoflegends.com/ko-kr/game-overview/` 잡음 (nav menu 오추출). 실제 첫 글 후보 html[1] sample = `.../ko-kr/news/game-updates/wild-rift-patch-no...` (정상).

## DOM evidence — wildrift list.html 의 data-testid 확인됨
```
data-testid="article-card-grid"
data-testid="articlefeaturedcard-component"
data-testid="card-title"
data-testid="card-date"
data-testid="card-description"
data-testid="card-image"
```
→ TFT 와 100% 동일 구조. TFT config 그대로 베껴 `site`/`board`/`url_template`/`Referer`/urljoin 호스트만 wildrift 로 교체하면 됨.

## TFT canonical config (N100 운영중)
경로: `configs/host_teamfighttactic_news_0e900726.json`. 핵심 selector:
- strategy: `httpx_html`
- url_template: `https://teamfighttactics.leagueoflegends.com/ko-kr/news/`
- row_selector: `section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"][href^="/ko-kr/news/"]`
- row_required_selector: `time`
- post_id from `:self` href + `regex_extract`: `/ko-kr/news/(?:[^/]+/)*([^/?#]+)/?$`
- title from `div[data-testid="card-title"]` text
- url from `:self` href + `urljoin` to base
- published_at from `time` attr `datetime` + iso8601
- author const "Riot Games"

## 작업
1. `configs/host_wildrift-league_news_8313486f.json` 작성 — TFT config base 로 site/url/board/Referer/urljoin host 교체. 다른 selector/transform 동일.
2. **스키마 검증**:
   ```
   python -c "import json; from engine.config_schema import validate_config; validate_config(json.load(open(r'configs/host_wildrift-league_news_8313486f.json',encoding='utf-8'))); print('OK')"
   ```
3. **스모크**:
   ```
   python -c "
   import asyncio, json; from engine.config_adapter import make_adapter
   c=json.load(open(r'configs/host_wildrift-league_news_8313486f.json',encoding='utf-8'))
   async def m():
       async with make_adapter(c) as a:
           ps=await a.fetch_list(page=1); print('list', len(ps))
           for p in ps[:3]: print(p.post_id, repr((p.title or '')[:50]), p.published_at)
           if ps: f=await a.fetch_article(ps[0]); print('body chars', len(f.content_html or ''))
   asyncio.run(m())"
   ```
   - 목록 ≥3건 + 본문 ≥1000자 = PASS.
   - 0건/0자면 selector/transform 정정.
4. `python scripts/register.py --config "configs/host_wildrift-league_news_8313486f.json"` 호출 — baseline 저장. FAILED.json/triage_queue 자동 cleanup.
5. **case 파일** `docs/cases/host_wildrift-league_news_8313486f.md` 작성. frontmatter:
   ```yaml
   ---
   slug: host_wildrift-league_news_8313486f
   url: https://wildrift.leagueoflegends.com/news/
   status: "✅ 등록"
   outcome: handcrafted
   date: 2026-05-28
   fix_layer: F
   failure_keys: [posts_nonempty, schema_invalid_source]
   config_strategy: httpx_html
   tags: [riot, next-js, gacha-global]
   ---
   ```
   body — 1줄 요약 + DOM evidence (data-testid 시맨틱 클래스 사용) + 동료 reference (TFT canonical) + Track B 6-layer audit (C hit candidate — first_article picker 가 nav menu 잘못 잡음, escalate 가능). 본문 §일반화 후보 섹션 = "Riot Next.js platform 모든 도메인이 `section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"]` 동형 — recognizer 신설 후보(F-layer). 단 이번 batch 의 TFT/wildrift 외 4 Riot endpoints 가 gate_reject/url_dead 라 정량 cluster=2 — recognizer 승급 cluster 미달. _deferred_heuristics.md 에 append 권장."
6. **cases_index**: `python scripts/cases_index.py --backfill-db output/cases.sqlite3`
7. **`_deferred_heuristics.md` 에 1줄 append** (Riot Next.js recognizer 후보):
   `- 2026-05-28: Riot Next.js platform recognizer (host=*.leagueoflegends.com OR riotgames.com news) — DOM=section[data-testid="article-card-grid"] a[data-testid="articlefeaturedcard-component"]. 현재 cluster: TFT(done) + wildrift(handcrafted) = 2 site. 4+ 도달 시 engine/recognizers/riot.py 발급.`
8. `probe_smoke.py --stage 3 --stage 5` exit 0 확인.

## 제약
- **stage/commit/push 금지**. worktree 안에 변경만 두고 STOP. main 직렬 merge 는 Claude (caller) 가 함.
- **dashboard/*, scripts/probe*.py, engine/strategies/*, engine/recognizers/* 건드리지 X** (이 task scope 아님).
- DPI/SNI 우회 X (`docs/크롤링 지침.md`).
- `headless: false` 박지 X (CLAUDE.md mem — N100 X server 없음).

## §0c-회피 게이트 4종 (Claude review)
1. probe artifact 없음 defer X — probe artifact 이미 있음 (`output/probe/host_wildrift-league_news_8313486f/`).
2. 일반화 신호 punt X — case body §일반화 후보 섹션 채워야 함 (Riot recognizer cluster 정량 + _deferred_heuristics append).
3. 처방-우선 task 추종 X — TFT canonical 검증 후 wildrift list.html 직접 봐서 DOM 일치 재확인 (probe artifact 의 list.html). 다르면 selector 수정.
4. `no_change` 정당화 불충분 X — 본 task 결과는 `handcrafted` outcome (등록 성공 시).

## 성공 게이트
- `register.py --config` rc=0 + state.json 생성
- 스모크 list ≥3건 + body ≥1000자
- probe_smoke stage 3+5 PASS
- case .md frontmatter 통과 + cases_index 재생성
