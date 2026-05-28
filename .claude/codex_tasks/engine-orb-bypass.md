# Task: engine F-layer — playwright_html `route_rewrite` config option for ORB bypass

## 배경 (cross-site brief 의무)

batch `2026-05-24-games-mobile-strategy-rpg` (100 entries) drain 후 13 active fail 처리 중:
- 11 처리 끝남 (REJECTED 2 + REGISTERED 2 via agentic + travian via codex sitemap config)
- 1 미해결: `https://afkjourney.farlightgames.com/news/`

afkjourney 분석 (codex prior session 정직 분석 + 추가 검증):
- live 200 OK, 진짜 게시판 (Farlight Games, Lilith CDN 형제)
- 정적 HTML: Vue template 1개 + inline `var news_list = '{...}'` 안에 814 article URL 들어있음
- Playwright (stealth on/off 무관): row 0건 — 외부 hydration script `https://dapcdn.63cj.com/common-utils/index.1.1.7.umd.js` 가 Chrome ORB(`net::ERR_BLOCKED_BY_ORB`) 로 차단되어 `reportH5SlsEvent` 초기화 fail → Vue row hydration 안 됨

**Root cause**: dapcdn 서버가 `.umd.js` 파일을 `Content-Type: text/html` 로 응답. Chrome ORB(Opaque Response Blocking) 가 content-type mismatch 라 script tag 통한 cross-origin script load 차단.

검증:
```
$ curl -sI https://dapcdn.63cj.com/common-utils/index.1.1.7.umd.js
HTTP/1.1 200 OK
Content-Type: text/html    ← 진짜 .js 인데 text/html
```

같은 batch 의 farlightgames.com/news = 같은 hydration ORB 차단인데 `#news_container .newspage` 가 server-side render 라 통과. afkjourney 는 client-side render 만 있어 차단되면 0건.

**일반화 가치**: dapcdn.63cj.com 은 Lilith CDN — 같은 그룹 다른 게시판도 같은 hydration script 의존 가능. wrong Content-Type 으로 ORB 차단되는 CDN 일반 패턴 (다른 사이트도 잠재 적용).

## 작업

### F-layer 신규 config option: `route_rewrite_response_headers`

`engine/strategies/playwright_html.py` 에 새 config option 추가:

```jsonc
{
  "strategy": "playwright_html",
  "route_rewrite_response_headers": [
    {
      "url_pattern": "https://dapcdn.63cj.com/**/*.js",
      "headers": {"content-type": "application/javascript"}
    }
  ]
}
```

구현:
- context.route(pattern, handler) 사용 (Playwright 내장)
- handler: `route.fetch()` 로 원본 응답 받기 → header 수정 → `route.fulfill(response=resp, headers=new_headers)`
- url_pattern 은 Playwright glob pattern (또는 regex 옵션 추가)
- 다중 entry 지원 (list)

### 후속 — afkjourney config 박기

위 engine 변경 후 `configs/host_afkjourney-farl_news_2382ee85.json` 신규 작성:
- strategy: playwright_html
- `route_rewrite_response_headers`: dapcdn 패치
- wait_selector: `a.news_item[href]` (hydration 후 href 박힘)
- row_selector: `div.news_list > a.news_item`
- post_id: href regex `/news/([0-9a-f]{32})/`
- title: `.title_box` text
- url: href urljoin
- article content: `div.news_content`

### 검증

1. `python -m py_compile engine/strategies/playwright_html.py`
2. `python scripts/probe_smoke.py --stage 3 --stage 5` PASS
3. afkjourney 스모크:
   ```python
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
   ```
   기대: list ≥ 19, body > 500 chars
4. farlightgames.com/news (이미 N100 등록됨, 회귀 없는지 확인) 도 스모크:
   ```python
   c = json.load(open('configs/host_farlightgames-c_news_becd128c.json',encoding='utf-8'))
   ```
   기대: list ≥ 7 (이전과 동일), body 동일

### case + commit

- `docs/cases/host_afkjourney-farl_news_2382ee85.md` 작성 (outcome=improved 또는 handcrafted — fix_layer 가 F+config, mechanism 은 generic engine extension + site config 1):
  - `fix_layer: F`
  - `outcome: improved` (engine ORB bypass 자체는 generic 추론 개선 — cross-site CDN 잘못 박힌 케이스 일반)
  - failure_keys: `var_news_list_inline_js`, `orb_blocked_hydration_cdn`, `posts_nonempty_zero`
  - config_strategy: playwright_html
  - tags: [engine-orb-bypass, lilith-cdn, farlight, vue-hydration]
- frontmatter Track B 6-layer audit: F hit (engine code), C maybe hit (probe heuristic 으로 `var <name>_list` 패턴 detect — escalate `_deferred_heuristics.md`)
- ship evidence: 사용자 명시 ("engine 개선해야지" + 이전 turn ship 요청)
- N100 deploy: 동일 절차 (commit + push → `ssh $DEPLOY_HOST 'bash ~/notice-watcher/scripts/n100_deploy.sh'`)
- **Claude 가 commit/push/N100 배포** — 본 worktree codex 는 HARD-STOP

## OUT OF SCOPE — 만지지 X

- `probe/extract.py` 휴리스틱 자체 신설 X (post-task: `_deferred_heuristics.md` 에 entry append)
- `prompts/config_writer.system.txt` 의 `route_rewrite_response_headers` 활용 룰 X (먼저 이 1 사이트 작동 검증 후 후속)
- 다른 strategy (httpx_html/json) X
- recognizer X

오직 `engine/strategies/playwright_html.py` + `configs/host_afkjourney-farl_news_2382ee85.json` + `docs/cases/host_afkjourney-farl_news_2382ee85.md`.

## probe artifact

`output/probe/host_afkjourney-farl_news_2382ee85/` (dev box 에 이미 있음. worktree gitignored 이라 worktree 안에서는 빔 — 필요 시 본인이 `python scripts/probe.py "https://afkjourney.farlightgames.com/news/"` 직접 실행).

## 회귀 검증 — 같은 batch 동료 sites

`configs/host_farlightgames-c_news_becd128c.json` (N100 등록 — 같은 dapcdn 의존). 본 engine 변경 후 회귀 없는지 확인 (현재 disable_stealth + wait_selector 로 통과 중 — route_rewrite 없이도 작동하므로 변경 무관).

## 기대 회귀

`probe_smoke.py --stage 3 --stage 5` 통과. existing 21+ configs 영향 0 (route_rewrite_response_headers 옵션 없으면 무동작).
