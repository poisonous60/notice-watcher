# Task: 2026-05-24-games-us batch 잔여 5 사이트 config 작성 + agentic prompt 개선

## 배경

`2026-05-24-games-us` batch 100건 drain 후 잔여 gen_fail 6건. 1건(annapurna)은 진짜 거부 대상(games 카탈로그, news 없음). 5건은 probe artifact 가 깨끗한데 agentic max_cycles 4-retry 모두 실패. agentic 이 selector 를 hallucination 하는 패턴.

사용자 명시 요청: **bethesda + store.epicgames 는 등록되거나 못 한다고 확인될 때까지 진행**. capability_blocked 핑계 punt 금지.

## 동료 sites (cross-site brief — §0c-0 의무)

같은 batch · 같은 failure mode (agentic max_cycles, probe data clean):

| slug | url | last_feedback | probe selector | probe first_article | platform |
|---|---|---|---|---|---|
| host_bethesda-net_news_29303712 | https://www.bethesda.net/news/ | posts_nonempty 0 (x2) | `div.bnetArticle-MuiGrid-root.bnetArticle-MuiGrid-container.bnetArticle-MuiGrid-spacing-xs-3 > div.bnetArticle-MuiGrid-root.bnetArticle-MuiGrid-item.bnetArticle-MuiGrid-grid-xs-12` cc=10 | https://www.bethesda.net/ko/article/3I4PnDOgukeCXjDpVXnV0H/fallout-76-season-25-preview | Material UI (bnetArticle-*) |
| host_bethesda-net_news_c5aa2960 | https://bethesda.net/news/ | published_at empty | (apex 도메인, 동일 board — www. 와 같은 /ko/news 도달) | 동 #29303712 | 동 |
| host_store-epicgames_news_16cc8b8f | https://store.epicgames.com/news/ | post_id_unique 중복 20건, title empty | `ul.css-1itgwkl > li.css-14gnlfd` cc=10 (sample=/blog/warhammer-skulls-2026-...) | https://store.epicgames.com/blog/warhammer-skulls-2026-announcements-updates | CSS-in-JS (Emotion css-XXXX) |
| host_epicgames-com_news_4655a152 | https://www.epicgames.com/news/ | probe_grounding_list_row_selector 0 nodes | `ul.css-1itgwkl > li.css-14gnlfd` cc=10 (sample=/blog/warhammer-skulls-2026-...) | https://www.epicgames.com/blog/warhammer-skulls-2026-announcements-updates | CSS-in-JS (동 epic) |
| host_deadbydaylight-_news_7eed0155 | https://deadbydaylight.com/news/ | article_body_len < 100 (content selector 못 잡음) | `div.container.grid-articles... > div.article-card.btnLines-large.relative.h-auto.w-full.text-white.bg-grayDarker` cc=9 (sample=/news/jason-comes-to-dbd/) + JSON API `/page-data/news/page-data.json` | https://deadbydaylight.com/news/jason-comes-to-dbd/ | Gatsby (page-data.json) + Tailwind |

(annapurna root 는 사용자가 별도 REJECT 결정 예정 — 이 task scope 아님)

## probe artifact 경로 (dev box)

- `output/probe/host_bethesda-net_news_29303712/`
- `output/probe/host_bethesda-net_news_c5aa2960/`
- `output/probe/host_store-epicgames_news_16cc8b8f/`
- `output/probe/host_epicgames-com_news_4655a152/`
- `output/probe/host_deadbydaylight-_news_7eed0155/`

각 디렉토리에 `list_candidates.json`, `list.html`, `article.html`, `article_candidates.json`, `diagnosis.json`, `traffic.har`, `s1.H2.html` 등 raw artifact 다 있음. **반드시 raw artifact 직접 까서** selector / pagination / article 구조 확인 후 config 작성.

## 해야 할 일 — 우선순위 순

### A. 5 사이트 config 작성 (`configs/<slug>.json`)

각 slug 별로 `configs/<slug>.json` 한 장씩. 베이스 = 기존 `configs/` 안의 비슷한 strategy (httpx_html / playwright_html) config 1-2개 보고 베껴 시작.

**selector 룰** (이번 batch 의 핵심 lesson):
- CSS-in-JS hash class (`css-1itgwkl`, `bnetArticle-MuiGrid-spacing-xs-3` 등) 는 build 마다 바뀌므로 **selector 박지 X**.
- href 패턴으로 semantic 매칭: `a[href^="/blog/"]`, `a[href*="/ko/article/"]`, `a[href*="/news/"]` 같이. row_required_selector 에 href 패턴 박고 row_selector 는 `li` `article` `div.article-card` 같은 일반 태그.
- 가능하면 JSON API 우선 (dbd 의 `/page-data/news/page-data.json` 같은). Gatsby/Next.js 사이트는 `_next/data/`·`page-data/` 류 prebuilt JSON 흔함.

**전략 선택**:
- bethesda: 정적 HTML 14KB shell — `playwright_html` 필수. Material UI render 후 DOM 에서 selector 매칭.
- store.epicgames / www.epicgames: live curl 403 Akamai. N100 playwright stealth 통과 → `playwright_html` + `disable_stealth: false` (기본).
- deadbydaylight: JSON API `/page-data/news/page-data.json` 가 200 OK → `httpx_json` 가능. 안 되면 `playwright_html` + `a[href^="/news/"]` row_required.

**article 본문 selector**: 각 site 의 `article.html` 직접 읽고 `<h1>` 위치 + content 컨테이너 확인. dbd 의 `article_body_len < 100` 은 LLM 이 잘못된 content selector 박은 것.

**url_template** = 실제 board URL (bethesda 는 `https://www.bethesda.net/ko/news/` 같이 locale path 박기).

**검증 (각 config 작성 후 의무)**:
```sh
# 1. 스키마
python -c "import json; from engine.config_schema import validate_config; validate_config(json.load(open(r'configs/<slug>.json',encoding='utf-8'))); print('schema OK')"

# 2. smoke
python -c "
import asyncio, json
from engine.config_adapter import make_adapter
c=json.load(open(r'configs/<slug>.json',encoding='utf-8'))
async def m():
    async with make_adapter(c) as a:
        ps=await a.fetch_list(page=1); print('list', len(ps))
        for p in ps[:3]: print(p.post_id, repr((p.title or '')[:50]), p.published_at)
        if ps:
            f=await a.fetch_article(ps[0]); print('body chars', len(f.content_html or ''))
asyncio.run(m())
"
```

list ≥ 3 + body chars > 100 = OK. 0 또는 fail 이면 selector/url 재검토.

### B. agentic prompt / heuristic 개선 — cross-site lesson

5/5 사이트가 같은 패턴(probe artifact clean인데 agentic selector hallucination) — A-layer/B-layer 자리:

1. `prompts/config_writer.system.txt` — 룰 1-2줄 추가 (제거/수정 금지, **추가만**):
   - "selector 박을 때 `list_candidates.html_repeating_patterns[0].selector` 를 verbatim 으로 우선 사용 — 한 글자도 바꾸지 마라."
   - "selector 안에 `css-[a-z0-9]{5,}` / `Mui[A-Z][a-zA-Z]*-[a-z]+-\d+` / `jss\d+` 같은 hashed class 가 보이면 build 마다 바뀌므로 **href 패턴 selector (`a[href^="/blog/"]`, `a[href*="/article/"]`) 로 대체** 후 row_selector 를 일반 태그(`li`, `article`)로 잡아라."
   - "JSON API candidate (`traffic_json_api_candidates` 또는 Gatsby `_next/data/`·`/page-data/`) 가 있으면 그쪽이 selector 보다 안정 — `httpx_json` strategy 우선 고려."

2. `generate/validate.py` 또는 `scripts/register.py` 의 retry feedback (D-layer):
   - `probe_grounding_list_row_selector: 0 nodes` 발생 시 retry feedback 에 probe 의 `html_repeating_patterns[0].selector` 와 `first_article_url` 박아 넘기기 (LLM 이 직접 매칭하게).

3. `probe/extract.py` 또는 `probe/_contract.py` (C-layer, optional):
   - `html_repeating_patterns[i].selector` 에 hashed class 가 있으면 `selector_stable_alt: "a[href^=\"<href_common_prefix>\"]"` 같은 안정 대안 키 추가 → prompt 가 그쪽 사용.

### C. 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` exit 0.
- 위 A 의 smoke test 가 5 사이트 다 통과 (또는 통과 안 되는 사이트 명시 + 이유).
- `python scripts/cases_index.py --backfill-db output/cases.sqlite3`.

### D. case 파일

각 slug 별 `docs/cases/<slug>.md` 작성 (frontmatter + body — `.claude/skills/hand-config/SKILL.md` §6.5 형식). outcome:
- `improved` = agentic prompt/heuristic 개선으로 같은 패턴 사이트들이 자동 회복 (B 변경 효과)
- `handcrafted` = per-site config 작성만 (A 변경)

fix_layer 정확히 (commit prefix 와 일치). 5/5 사이트가 같은 lesson 이면 generic case `docs/cases/_generic_agentic_selector_grounding_2026-05-27.md` 한 장 + 5 site case 가 그걸 reference.

## HARD-STOP (codex 반드시 지킬 것)

- **commit / push / N100 배포 금지** — Claude 가 후속 검토 후 진행.
- **`git add -A` / `git commit -am` 금지** — staged 무관 파일이 다른 세션 작업일 수 있음 (CLAUDE.md §9b).
- **작업 끝나면 STOP**. 결과 result.md 에 적은 후 종료.

## §0c-회피 게이트 점검 (codex 자가 audit)

- (1) probe artifact 안 까고 가설로 config 작성 금지 — 반드시 `list_candidates.json` + `list.html` 직접 read.
- (2) 5 사이트가 같은 패턴 보이는데 "이 사이트 전용" 으로 punt 금지 — cross-site lesson (B 변경) 반드시 1-2 줄이라도 박을 것.
- (3) `no_change` outcome 정당화 시 6-layer (E/D/C/B/A/F) miss 이유 각각 1줄 + ship evidence 확인.
- (4) capability_blocked 핑계로 빠지지 X — 사용자 명시 요청 = 등록 시키거나 *진짜* 안 되는 이유 명확히.

## 결과 보고 형식 (result.md 마지막에)

```
## 결과
- registered (smoke OK):  <slug 목록>
- registered (smoke FAIL, but config 박힘): <slug 목록 + 이유>
- 진짜 안 됨 (capability/structural): <slug 목록 + verbatim 차단 신호 + 시도한 것>

## generic 개선
- prompts/config_writer.system.txt: <추가한 룰>
- generate/validate.py 또는 다른 자리: <변경>

## 다음 batch retry 권고
- `python scripts/remote.py batch-register --catalog=2026-05-24-games-us --failed gen`

## 변경 파일 목록
- configs/<slug>.json  (x5)
- prompts/config_writer.system.txt
- (기타)
- docs/cases/<slug>.md  (x5)
- docs/cases/_generic_*.md (1)
```
