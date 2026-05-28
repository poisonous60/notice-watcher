# Task: ship 2 sites (afkjourney/news + travian/international/news) — manual configs

## Context (cross-site brief, 의무 — agentic-first guard)

batch `2026-05-24-games-mobile-strategy-rpg` (100 entries, mobile game studio /news/ subpath) drain 후:
- registered 11, 자동거부 rc=2/3/4 76 (정상 marketing landing/dead URL/locale gate)
- gen_fail rc=1 3건: zlongame(404)+stateofsurvival(503) REJECTED, lilith/news ship 성공(playwright_html agentic) ✅
- cap_blocked rc=5 10건: RSS OOM heavy SPA, 별도 처리

남은 ship 2건 (사용자 명시 요청 — Track A 진입 조건 충족):

| slug | URL | live | 현 상태 |
|---|---|---|---|
| `host_afkjourney-farl_news_2382ee85` | https://afkjourney.farlightgames.com/news/ | 200 OK | rc=1 dev gen_fail (agentic max_cycles ×2, --article-url 도 실패) |
| `host_travian-com_international_993a586a` | https://www.travian.com/international/news/ | 200 OK | dev agentic "성공" 했지만 `row_selector: "#root"` + `post_id: const "root"` = **fake config 1 row** (실제 게시판 파싱 X). 교체 필요 |

**cross-site 일반화 후보 0건 audit 결과** (위 두 사이트 각자 별개):
- afkjourney: 정적 HTML 풍부 (lilith CDN 형제 — `<a class="news_item">` 행 19개), agentic 가 선택 오류만 한 단순 케이스
- travian: SPA shell (모든 path 같은 HTML 반환), sitemap.xml 로 게시 (`/international/news/YYYY/MM/DD/<slug>/`)

각각 별 패턴 → per-site Track A 필요. agentic-first 자리 없음 (이미 시도 후 fail).

## Site 1: afkjourney/news

**probe artifact**: `output/probe/host_afkjourney-farl_news_2382ee85/` (이미 존재, dev 재실행 결과)

**Raw evidence** (`output/probe/host_afkjourney-farl_news_2382ee85/list.html` 정적 응답):
```html
<a href="/news/e10fe489080baa333e03ce2a5a7fa34c/" class="news_item">
  <div class="item_content">
    <div class="content_l">
      <div class="content_title">
        <div class="title_box">5/7(목) 버전 업데이트 알림 (버전 1.6.4)</div>
      </div>
      <div class="content_box">
        <div class="content">5/7(목) 버전 업데이트 알림 (버전 1.6.4)</div>
        <div class="date"> 05/07/2026</div>
      </div>
    </div>
  </div>
</a>
```

행 약 19개. 컨테이너: `<div class="news_list">`.

post_id pattern: `/news/([0-9a-f]{32})/` (lilith 형제와 동일).

**target config**: `configs/host_afkjourney-farl_news_2382ee85.json`
- strategy: `httpx_html` (정적 충분 — probe verdict 도 "정적 HTTP로 충분")
- url_template: `https://afkjourney.farlightgames.com/news/`
- row_selector: `div.news_list > a.news_item` (또는 `a.news_item`)
- post_id: from href, regex_extract `/news/([0-9a-f]{32})/`
- title: `div.title_box` text
- url: href, urljoin
- date: `div.date` text (선택)
- article content: `div.news_content` 또는 본문 컨테이너 (article.html 보고 결정)

**참고 사이트** (방금 등록 성공): `configs/host_lilith-com_news_6b1370c1.json` — 형제 (lilith CDN). 단 lilith 는 playwright_html (locale=zh_CN 인터랙티브 필요). afkjourney 는 정적 OK 가능성.

## Site 2: travian/international/news

**Probe artifact**: `output/probe/host_travian-com_international_993a586a/` (이미 존재)
**Current fake config**: `configs/host_travian-com_international_993a586a.json` (교체 대상)

**Raw evidence**:
- `https://www.travian.com/international/news/` = SPA shell (HTML=0 candidates)
- 모든 path (`/news/feed`, `/news/1440`, `/news/2026/...`) 같은 shell 반환
- `https://www.travian.com/sitemap.xml` = 진짜 source. news article URL pattern:
  ```
  <loc>https://www.travian.com/international/news/2026/05/26/mobile-app-3-12/</loc>
  <loc>https://www.travian.com/international/news/2026/05/21/changelog-467-2/</loc>
  <loc>https://www.travian.com/international/news/2026/05/20/eid-al-adha-truce/</loc>
  ...
  ```
- 같은 sitemap 에 다른 path 도 섞임. filter 필요: `/international/news/[0-9]{4}/`.

**target config**: `configs/host_travian-com_international_993a586a.json` (교체)

옵션:
1. **httpx_html with sitemap parsing** (가능하면 선호 — 가벼움). url_template = sitemap.xml. row_selector = XML 의 `<url>` 노드 중 `/international/news/[0-9]{4}/` 매치. lxml 가 XML parsing OK.
2. **playwright_html with wait for hydrated content** (SPA hydration 후 article 행 노출되면). 시도해서 wait_selector + row_selector 잡을 수 있는지 확인.

sitemap option 이 robust (안티-봇 우회 불요, 가벼움, 신뢰).

post_id 추출 — URL last path segment 또는 `YYYY/MM/DD/slug` 전체:
- `regex_extract: /international/news/([^/]+/[^/]+/[^/]+/[^/]+)/?$` → `2026/05/26/mobile-app-3-12`

title — sitemap 에는 title 없음. **fetch_article** 시 `<title>` 또는 `<h1>` 에서 가져옴 (config 의 `article.fields.title` 또는 자동). 시도.

published_at — sitemap `<lastmod>` 있으면 활용.

## 작업 절차

### afkjourney (먼저, 간단)
1. `configs/host_afkjourney-farl_news_2382ee85.json` 작성 (httpx_html 시도).
2. 스모크:
   ```bash
   python -c "
   import asyncio, json
   from engine.config_adapter import make_adapter
   c = json.load(open(r'configs/host_afkjourney-farl_news_2382ee85.json',encoding='utf-8'))
   async def m():
       async with make_adapter(c) as a:
           ps = await a.fetch_list(page=1)
           print('list', len(ps))
           for p in ps[:3]: print(' ', p.post_id, repr((p.title or '')[:60]))
           if ps:
               f = await a.fetch_article(ps[0])
               print('body chars', len(f.content_html or ''))
   asyncio.run(m())
   "
   ```
3. list ≥ 10 + body > 500 chars 면 OK. 아니면 selector 조정.
4. 0건이면 `strategy: playwright_html + wait_selector: a.news_item` 로 fallback.
5. `python scripts/register.py --config configs/host_afkjourney-farl_news_2382ee85.json` 으로 등록 (baseline 박힘).

### travian (다음, 복잡)
1. **sitemap option 먼저** — `configs/host_travian-com_international_993a586a.json` 교체:
   - strategy: `httpx_html`
   - url_template: `https://www.travian.com/sitemap.xml`
   - row_selector: XML `<url>` 안 loc 가 `/international/news/[0-9]{4}/` 매치인 것 (XPath 또는 CSS 사용 가능 여부 lxml 확인)
   - 또는 url_template 을 직접 sitemap-news.xml 류 (있다면)
2. 스모크 위와 동일 — list ≥ 5 + body > 300 chars.
3. 안 되면 playwright_html 로 SPA hydration 시도 (wait_selector 가 article 행 노출 후).
4. 안 되면 case_log `no_change` + 사용자에게 fail 보고.

### case + commit (양쪽 등록 성공 시)
- 각 slug `docs/cases/<slug>.md` 작성. frontmatter:
  ```yaml
  ---
  slug: host_afkjourney-farl_news_2382ee85
  url: https://afkjourney.farlightgames.com/news/
  status: "✅ handcrafted"
  outcome: handcrafted
  fix_layer: none
  failure_keys:
    - agentic_max_cycles
    - posts_nonempty_zero
  config_strategy: httpx_html  # 실제 strategy 박기
  requested_by: user (batch ship request)
  date: 2026-05-27
  ---
  ```
- body: 진단 (probe 신호) + Track B 6-layer audit (모두 miss 이유) + Track A ship evidence (사용자 batch ship 요청).
- `python scripts/cases_index.py --backfill-db output/cases.sqlite3`
- 본인 (codex worktree) 은 **commit 하지 X** — HARD-STOP. Claude 가 review + merge + commit + push.

### 안 되면 honestly stop
- agent did not produce a passing config → 사이트별 case body 에 stop 이유 명시. fake config (1-row const) **절대 박지 X** (travian 처음 시도가 그 함정).

## probe artifact 경로
- afkjourney: `output/probe/host_afkjourney-farl_news_2382ee85/` (list.html 1.9MB, list_candidates.json, article.html)
- travian: `output/probe/host_travian-com_international_993a586a/` (list.html SPA shell, sitemap_candidates 100 in diagnosis.json)

## 형제 batch 동료 sites (cross-site context)
이미 처리 끝난 86건 (rc=2/3/4 자동거부 76 + registered 11):
- registered 11: marvelstrikeforce/root, startrekfleetco/news, puzzlesandsurvi/root, centurygames/root+news, goodgamestudios/root, warrobots/news, wotblitz/news, farlightgames/news, kabam/news, skillz/news (이미 11개는 정적 HTTP 통과)
- 자동 REJECTED rc=2/3/4: 거의 marketing landing/dead URL/locale redirect. 정상 거부.

대상 2개 모두 *real board* 인데 generic 추론이 못 푼 잔여. cross-site 일반화 가능한 패턴 신호 부재 — site 별 idiosyncratic config 필요.

## OUT OF SCOPE — 만지지 X
- `prompts/` 어느 것도 X (agentic 가 이번 케이스 못 푼 건 사이트 별 idiosyncratic, generic prompt fix 자리 아님)
- `engine/recognizers/` 신설 X (단일 사이트, recognizer 자리 아님)
- `probe/`, `generate/`, `scripts/register.py` X
- 다른 slug 의 config X

오직 `configs/host_afkjourney-farl_news_2382ee85.json` (신규) + `configs/host_travian-com_international_993a586a.json` (교체) + `docs/cases/host_*.md` (신규) + `docs/cases/INDEX.md` (cases_index 가 regen).
