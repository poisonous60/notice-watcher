# config 기반 크롤링 엔진 가이드

신규 사이트를 **사람이 어댑터 코드를 짜는 대신**, 경량 LLM(Gemini)이 선언적 **config(JSON)** 를 작성하고
범용 엔진(`engine/`)이 그 config 를 실행하는 워크플로우. 어려운 사이트(Cloudflare 챌린지 등)는 손으로 짠
어댑터를 `strategy: "handwritten"` config 로 감싸 동일 파이프라인에 올린다.

```
사용자가 링크 입력
  → 경량 probe (scripts/probe.py --lite)
  → preflight (register.py — gemini 부르기 *전에* 1회): probe 가 잡은 첫 글 페이지를 Playwright+HAR 로 re-probe
     (본문 JSON API 후보 / 렌더된 DOM 확보) + probe 신호로 목록 전략 hint(목록이 JS-gated 면 httpx_json/playwright_html) 미리 주입
  → digest 구성 (engine/digest.py — 정제 HTML + probe 후보 + 통과 헤더 + hydration + 위 hint·본문 API 후보)
  → Gemini 가 config JSON 작성 (generate/) — structured(JSON) 출력
  → 엔진이 config 실행 + 자동 검증 (3층위) — 실패하면 피드백 주고 재생성 (≤4회 = --max-attempts, 2라운드부터 사실상 partial regen)
  → 통과: configs/<name>.json 저장 + output/poll_state/<slug>.json (baseline = 현재 글 집합)
     실패: <slug>.FAILED.json + "손으로 config/어댑터 작성 필요" 안내 (→ docs/사이트 어댑터 추가 가이드.md)
  → 매 폴링(scripts/poll.py): config 실행 → post_id diff 로 새 글 감지 → output/collected/<ts>/ 에 기록
     → 깨짐 신호(에러 / 0건인데 페이지엔 글 있음 / post_id·title 급변) 연속 2회 → 자동 재-probe + 재생성
```

---

## 1. 빠른 사용

```bash
# 의존성 (1회)
pip install -r requirements.txt
playwright install chromium

# Gemini 키 (택1)
#   환경변수 GEMINI_API_KEYS=키1,키2,...   (여러 개 — 429 나면 다음 키로 자동 전환)
#   환경변수 GEMINI_API_KEY=키
#   파일      GEMINI_API_KEY.md  (한 줄에 키 하나)
# 모델: 기본 gemini-2.5-flash. 다른 모델은 GEMINI_MODEL=gemini-3-flash-preview 처럼 지정.

# 사이트 등록 (URL → config + baseline). 알려진 플랫폼(네이버·다음 카페, 아카, 디시 미니갤, 넥슨 포럼, 네이버 게임 라운지)이면 probe/gemini 없이 즉시 등록.
python scripts/register.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="
python scripts/register.py "<목록URL>" --out configs/my_board.json --max-attempts 4
python scripts/register.py "<목록URL>" --article-url "<실제 글 하나 URL>"   # probe 가 '첫 글'을 잘못 잡는 사이트용 힌트(↓ §4)
python scripts/register.py "<목록URL>" --no-recognize                      # 알려진 플랫폼 인식 끄고 probe→gemini 강제(디버그)

# 손으로 짠 config(handwritten strategy 등)를 그대로 등록 (probe/gemini 생략)
python scripts/register.py --config configs/arca_akendfield.json

# 폴링 (등록된 사이트 전부)
python scripts/poll.py
python scripts/poll.py --sites <slug1>,<slug2> --max-new-articles 5
python scripts/poll.py --no-reprobe        # 깨져도 재-probe 안 함(리포트만)

# (디버그) probe → digest → config 만 보고 싶을 때
python scripts/probe.py "<URL>" --lite
python -m engine.digest "<probe-slug>" --out digest.json
python scripts/gen_config.py "<URL>" --escalate --sanity

# config 만 검증 (네트워크 없음)
python scripts/demo_config.py --check-all
```

산출물:
- `configs/<name>.json` — 생성/등록된 config (커밋 대상)
- `output/poll_state/<slug>.json` — 등록 상태 + 본 글 post_id 집합 + 연속 깨짐 카운터 (gitignore)
- `output/poll_state/<slug>.FAILED.json` — 자동 등록 실패 마커 (마지막 config + 피드백)
- `output/collected/<ts>/{summary.txt, <slug>.new.json}` — 폴링 결과(새 글)
- `output/probe/<slug>/` — probe 산출물 (digest 의 입력)

### register.py 의 처리 순서
1. **알려진 플랫폼 인식** (`engine/recognizers/` 패키지, `--no-recognize` 면 생략) — URL 이 *이미 손어댑터/검증된 config 패턴이 있는 플랫폼*(네이버 카페·다음 카페·아카라이브·디시 미니갤·넥슨 포럼·네이버 게임 라운지·Reddit)이면 그 자리에서 config 를 만들어 `fetch_list` 로 글이 1건 이상 잡히는지 확인하고 바로 등록 — **probe·Gemini 안 돌림**. 잘못 인식했으면(글 0건/예외) 조용히 2번으로 폴백. 같은 플랫폼의 새 게시판은 `cafe_id`/`board`/`channel` 만 다르므로 이걸로 즉시 잡힘.
2. **probe → preflight(글페이지 HAR re-probe + probe 신호 hint) → digest → Gemini(검증 재시도 ≤max_attempts) → 검증** — 1에서 안 잡힌 사이트. (아래 §4.)
3. **`--config <path>`** — 사람이 손으로 짠 config 를 그대로 등록(probe/Gemini 둘 다 생략, `fetch_list` 로 baseline 만).

→ 새 플랫폼을 손어댑터/손config 로 한 번 처리했으면 `engine/recognizers/<plat>.py` 한 파일 추가 (`NAME` + `PATTERNS=[(re.Pattern, builder), ...]` export) → auto-discovery 가 잡아 그 플랫폼의 다음 게시판은 자동으로 1번에서 처리된다.

---

## 2. config 스키마

상세 docstring: `engine/config_schema.py`, `engine/extract_helpers.py`. 핵심만:

```jsonc
{
  "version": 1,
  "site": "cse.skku.edu",        // NoticePost.site
  "board": "1582",               // NoticePost.board + url_template 의 {board}
  "strategy": "httpx_html",      // "httpx_html" | "httpx_json" | "playwright_html" | "handwritten"
  "headers": { "User-Agent": "...", "Referer": "..." },   // httpx_*/playwright_*
  "timeout": 15.0,
  "proxy_url": null,             // "{target}" 자리에 URL-encoded 원본 (httpx_* 만)
  "polite_sleep": { "min": 30.0, "max": 35.0 },  // 선택. 엔진 기본(3~6s)보다 *느릴 때만* 적용(=하한). robots Crawl-Delay 반영용.

  // strategy == "handwritten" 일 때:
  "adapter": "ArcaLiveAdapter",  // adapters 패키지의 클래스명
  "kwargs": { "channel": "akendfield", "include_notices": true },

  // playwright_html 추가 키 (최상위):
  "storage_state_path": "output/state/xxx.json",   // 로그인 세션 재사용(파일 있으면 로드)
  "headless": true, "nav_timeout_ms": 30000, "idle_timeout_ms": 15000,

  "list": {
    "url_template": "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1={board}&srSearchKey=&srSearchVal=",
    "pagination": { "kind": "offset", "offset_param": "article.offset", "page_unit": 10,
                    "extra_params_when_paged": { "articleLimit": "10" } },
    // kind="query_param": 1페이지 포함 page_param=페이지, size_param=크기 를 항상 붙임
    // kind="offset": 2페이지부터만 offset_param=(page-1)*page_unit, size_param=page_unit, extra_params_when_paged 를 붙임
    "page_size_max": 20,         // 선택 — 서버가 페이지크기를 cap 하는 경우

    // --- httpx_html / playwright_html ---
    "row_selector": "ul.board-list-wrap > li",
    "row_required_selector": "dt.board-list-content-title",   // 선택 — 행 안에 이게 없으면 그 행 스킵(광고/구분선 제거)
    "exclude_selector": ".notice-service",                    // 선택 — 이 CSS 에 매칭되는 행 제거
    "include_notices": true,
    "notice_class_absent": "us-post",                         // 선택 — include_notices=false 일 때, 이 class 없는 행을 공지로 보고 제거
    "wait_selector": "a.vrow",                                // playwright_html 전용 — 이 요소 나타날 때까지 대기

    // --- httpx_json ---
    "list_path": ["data", "list"],          // 목록 배열까지의 JSON 경로
    "item_path": ["item"],                  // 선택 — 각 배열 원소 안에서 글 dict 위치
    "type_field": "type", "type_allow": ["ARTICLE"],   // 선택 — 원소의 type_field 값이 type_allow 안에 있어야 채택
    "success_when": { "path": ["code"], "equals": 0 },  // 선택 — payload 수준 성공 체크

    // --- 공통: 글 한 건에서 뽑을 필드. post_id 와 title 은 필수. ---
    "fields": {
      "post_id":     [ { "from": "attr", "selector": "dt.board-list-content-title a", "attr": "href",
                         "transform": [["regex_extract", "[?&]articleNo=(\\d+)"]] } ],
      "title":       [ { "from": "css", "selector": "a.subject", "text": true, "transform": [["collapse_ws"]] } ],
      "url":         [ { "from": "attr", "selector": "a", "attr": "href", "transform": [["urljoin", "https://x"]] } ],
      "published_at":[ { "from": "css", "selector": "td.date", "attr": "title",
                         "match": "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$",
                         "transform": [["replace", " ", "T"], ["append", "+09:00"]] },
                       { "from": "css", "selector": "td.date", "text": true } ],
      "author": [...], "category": [...], "summary": [...], "cover_image": [...]
    }
  },

  "article": {
    "url_template": "https://x/api/bulletin/{post_id}",   // 선택 — 없으면 post.url 사용. {post_id},{board} 치환
    "fetch_kind": "html",        // "html" | "json" (기본: list strategy 계열)
    "wait_selector": "...",      // playwright_html 전용
    "skip_status": [401, 403],   // 선택 — 이 상태코드면 본문 비워서 반환(차단 우회 안 함)
    "success_when": {...},       // json 전용
    "data_path": ["data"],       // json 전용 — 본문 객체까지의 경로. content/enrich/re_extract 는 이 기준 상대
    "content": [ { "from": "css", "selector": "div.write_div", "html": true },
                 { "from": "css", "selector": ".writing_view_box", "html": true } ],
    "enrich": { "title": [...], "published_at": [...] },   // 선택 — 현재 None/빈 값인 필드만 본문 페이지에서 보강
    "re_extract": true           // 선택, json — 본문 payload(data)에서 list.fields 재추출해 None 아닌 값으로 덮어씀(엔드필드 케이스)
  }
}
```

### source `from` 종류 (fallback chain — 리스트 안에서 앞에서부터 시도, None 아닌 첫 결과 채택)
| `from` | 의미 |
|---|---|
| `css` | `selector` 의 요소 텍스트(`text:true`, 기본) / `attr` / `html:true`. `match`(추출값이 정규식에 안 맞으면 실패), `pick:"first_matching"`+`match`(여러 요소 중 텍스트가 맞는 첫 요소), `joiner`(텍스트 join 문자, 기본 " "). **`selector` 를 빼거나 `":self"` 면 행(row) 요소 자체** — `row_selector` 가 `a.vrow` 처럼 반복 행이 곧 링크일 때 post_id/url 을 그 href 에서 뽑는다 |
| `attr` | `css` + `attr` 필수 의 별칭 |
| `json` | `path`(키=문자열, 인덱스=정수) 로 navigate. httpx_json 의 fields / article.content 에서 |
| `const` | `value` (null 가능) |
| `template` | `value` 를 `{board}/{post_id}/(같은 행에서 먼저 추출된 다른 필드)` 로 `.format` |
| `concat` | `parts:[ {const:"["} \| {field:"category"} \| <source dict> ... ]` 이어붙임. `{field}` 는 *먼저 선언된* 필드 참조(어떤 part 라도 None 이면 concat=None) |
| `class_present` | (css 행 전용) `class` 가 있으면 `"true"` 없으면 `"false"`. `negate:true` 면 반대 |

각 source 에 `"transform": [["name", args...], ...]` 체인. 추출 raw 값에 순서대로 적용(중간 None 이면 중단). 예외 나면 그 source 실패 → 다음 fallback.

### transform 라이브러리 (이 목록 밖은 금지 — `engine/transforms.py`)
`urljoin(base)` · `strip_query_fragment` · `regex_extract(pattern, group=1)` · `collapse_ws` · `remove_prefix(prefix)` ·
`strip_brackets`(`[학사]`→`학사`) · `replace(old, new)` · `append(suffix)` · `prepend(prefix)` · `strip` · `to_str` ·
`lower` · `upper` · `zero_pad(width)`(`"751"`→`"0751"`) · `iso8601(formats, tz=None)`(strptime 후 ISO) ·
`date_only_to_iso(tz)`(`"2026-05-11"`→`"2026-05-11T00:00:00+09:00"`) · `unixtime_to_iso(tz, unit)`(유닉스초/ms→ISO; tz="Z" 면 UTC) · `default(fallback)`

`NoticePost` 고정 필드: `site, board, post_id, title, url, published_at(ISO8601), author, category, summary, content_html, cover_image, raw(dict)`.

---

## 3. strategy

| strategy | 진입 | 대응(원본) | 비고 |
|---|---|---|---|
| `httpx_html` | httpx GET → bs4 CSS select rows | dcinside, skku_cse | verdict "정적 HTTP 충분" + html_repeating_patterns 가 있으면 보통 이것 |
| `httpx_json` | httpx GET → JSON 경로로 목록 배열 | endfield, navercafe(단일 호스트 부분) | list_candidates.traffic_json_api_candidates 가 있으면 |
| `playwright_html` | chromium(+playwright-stealth, 있으면) 렌더 → bs4 CSS | arca(부분) | fields 스키마는 httpx_html 과 동일 + `wait_selector`. **Cloudflare 챌린지가 강한 사이트는 기본 `goto+networkidle` 로 부족** — 그런 사이트(arca 등)는 `handwritten` 으로 |
| `handwritten` | `adapters` 패키지의 기존 클래스 인스턴스화 | arca(ArcaLiveAdapter), navercafe(NaverCafeAdapter) | config 로 표현 안 되는 케이스. `adapter`+`kwargs` 만 적으면 됨. `register.py --config <path>` 로 등록 |

엔진(`engine/config_adapter.py:ConfigAdapter`)은 `BaseAdapter` 를 상속 → `adapters/runner.py:collect_parallel` 가 손으로 짠 어댑터와 동일 취급. `host` 는 config 값을 안 믿고 list url 의 netloc 에서 직접 유도. polite_sleep 은 엔진 공통(3~6s + ±30% jitter) 이 하한이고 config 의 `polite_sleep` 가 더 느린 값을 주면 그게 적용됨.

---

## 4. 검증 3층위 (`generate/validate.py:validate_built_config`)

생성된 config 로 실제 fetch 해서:
- **층위 1 (하드 — 실패하면 재생성)**: `fetch_list` 동작 / ≥1건 / `post_id` 유니크·비어있지않음·안정적 모양(공백 없는 짧은 ID) / `title` 비어있지않음 / `published_at`(있으면) ISO8601 파싱 / 첫 글 `fetch_article` 본문 ≥100자 (또는 첫 글들이 전부 `skip_status` 면 보류)
- **층위 2 (소프트 — 경고만)**: 생성 목록의 글 URL 이 probe 의 `first_article_url` 과 관련 있나 / 건수가 probe 후보 child_count 와 같은 ballpark 인가

`generate/generator.py:generate_config_validated` 가 이걸 ≤`max_attempts`(기본 4) 회 돌린다. 1라운드는 새 프롬프트, 2라운드부터는 "이전 config + 무엇이 FAIL 했나 + 실제 추출된 글들 + 수정 힌트" 를 주고 *수정* 요청(=사실상 partial regen). **gemini 호출은 사이트당 이 한 라운드(≤max_attempts)뿐** — 옛날엔 "lite gen 4회 실패 → full probe + gen 4회 → 본문 hint + gen 4회 …" 식으로 escalate 해서 최대 16회까지 불렀지만, 이제 그 정보를 ↓ preflight 로 처음부터 다 주고 한 라운드만 돌린다.

**preflight** (`register.py:_preflight` — gemini 부르기 *전에* 1회 실행. `--no-escalate` 면 통째로 생략):
1. **첫 글 페이지 render+HAR re-probe** — *단, probe 가 잡은 첫 글 URL 이 신뢰할 만할 때만*. `register.py:_best_article_url` 이 probe 후보들(`article_sample.url` / `first_article_url` / `html_repeating_patterns[].sample_url`) 중 점수 가장 높은 걸 고른다(같은 호스트 +4, 글ID 숫자 +2, `view/detail/article/...` 류 경로 +1). 점수 ≥4(= 최소 같은 호스트)면 → `_set_first_article_url` 로 그 URL 을 `list_candidates.json` 의 `first_article_url` 에 박고 → Playwright 로 다시 열어 `article.html`(렌더된 DOM, digest 가 자동으로 더 큰 쪽을 글 샘플로 씀) + `output/probe/<slug>/article_candidates.json`(본문을 담은 JSON XHR 후보 — `probe/extract.py:traffic_article_body_candidates`, `traffic.article_click.har` 도 본다)을 만든다. `build_user_prompt` 가 이 후보들을 "⚡ 글 본문 JSON API 후보" 블록으로 자동 첨부 → 본문 API 를 쓰는 config(`article.fetch_kind:"json"`) 또는 `strategy:"playwright_html"` 로 유도. (본문이 정적 HTML 에 멀쩡히 있는 사이트면 후보 0건이지만 렌더된 DOM 샘플은 더 깨끗함.)
   - **점수 <4(= 같은 호스트도 아님 — probe 가 외부 링크를 첫 글로 오인)면 re-probe 를 건너뛴다** — 엉뚱한 페이지를 re-probe 해봤자 잘못된 `article.html` 샘플로 LLM 만 오도하므로. 대신 hint 로 "probe 가 첫 글을 외부 링크로 오인했다, `list_html` 의 글 행 href 를 직접 봐라, 안 되면 `--article-url`" 을 준다. 첫 글 URL 자체가 아예 없으면(목록 행이 `javascript:`/인라인 JS) "html_repeating_patterns/inline_js_data_candidates 를 봐라, 안 되면 handwritten" hint.
2. **probe 신호 기반 목록 전략 hint** (`register.py:_list_strategy_hint`): 목록 페이지가 정적 GET(httpx)으론 200 OK 가 안 나왔으면(`static_ok_preset` 없음 = headless 로만 됨 — JS 렌더거나 일시 차단) — 목록 JSON API 후보가 있으면 "`strategy:"httpx_json"` 검토하되 *그 후보가 진짜 글 목록인지* `list_html`/HAR 와 대조 확인 후(광고 SDK 가 점수 순위에 섞일 수 있다)", 없으면 "`html_repeating_patterns` 중 진짜 글 목록인 걸 골라 `strategy:"playwright_html"`(`row_selector`/`wait_selector`)" 를 `digest.escalation_hint` 에 넣어 1회차부터 제공. `static_ok_preset` 이 있으면(정적 GET 됨) 강제 안 하고 LLM 이 `list_html`/후보 보고 판단하게 둔다.

> ⚠ **preflight hint 는 "지침"이 아니라 "휴리스틱 힌트"다.** probe 의 첫 글 픽·후보 relevance 순위·전략 추정은 자주 틀린다(메뉴/사이드바/서브게시판 링크를 글로, 광고 SDK 를 목록/본문 API 로 집는 등). 그래서 프롬프트의 그 블록 헤더는 "⚠ probe 분석 힌트 (휴리스틱이라 틀릴 수 있음 — HTML/HAR 와 대조해 확인 후 반영. 어긋나면 실제 데이터를 따라 골라라)" 이고, `config_writer.system.txt` 의 "digest 읽는 법" 도 "사용자 입력(`--article-url`)은 신뢰하되 probe 휴리스틱은 raw 데이터와 대조 확인 후 — 맞으면 따르고 어긋나면 직접 골라라" 라고 한다. (사용자가 `--article-url` 로 *직접 준* 글 URL 은 신뢰한다. probe 가 *자동으로 추정한* 것만 "확인하고 써라".)

전부 실패하면 `<slug>.FAILED.json` + "손으로 config/어댑터 작성" 안내. (probe 가 첫 글을 잘못 집은 게 의심되면 ↓ `--article-url` 로 재시도.)

**`--article-url <글URL>` 힌트** (`register.py`, 그리고 봇 `/preview`·`/watch` 의 선택 인자 `article_url`): probe 의 "첫 글" 자동 탐지(`pick_first_article_url`)가 사이드바/메뉴 링크를 글로 잘못 집는 사이트가 있다(예: 넥슨 포럼 — `board_list?board=1018` 에서 서브게시판 링크 `board_list?board=1618` 를 첫 글로 집음). 그러면 preflight 의 re-probe 도 엉뚱한 페이지를 열고, LLM 이 받은 글 샘플·`article.url_template` 추측이 다 어긋난다. `--article-url` 을 주면 preflight 대신 — `list_candidates.json` 의 `first_article_url` 을 그 URL 로 교정하고 그 글페이지를 render+HAR 로 re-probe 해서 digest 의 `article_sample`(html/api_candidates/url)을 그걸로 맞춘 뒤, "이 글페이지 기준으로 article 을 잡고 list 의 post_id/url 필드도 이 글 ID 에 맞춰라"는 강한 `escalation_hint` 와 함께 1회차부터 생성한다.

---

## 5. 폴링 & 깨짐 처리 (`scripts/poll.py`)

매 폴링: `output/poll_state/*.json`(`.FAILED.json` 제외) 순회 → 각 config 로 `fetch_list` → `new = 현재 post_id − seen_post_ids` → 새 글 본문 fetch(상한 `--max-new-articles`, polite_sleep) → `output/collected/<ts>/<slug>.new.json` → `seen_post_ids` 갱신.

**깨짐 신호** (= "새 글 0개" 와 구분): ① `fetch_list` 에러 ② 0건인데 이전엔 글이 있었음 ③ `post_id` 가 갑자기 공백 포함 등 이상한 모양 / `title` 이 대부분 빔. 깨짐이면 `consecutive_breakage++`. **연속 2회** 되면 `register.py` 를 자동 재실행(re-probe + 재생성, 옛 config 는 `.bak` 보관, 실패 시 복구 + 유지보수자 확인 필요 로그). `--no-reprobe` 면 리포트만.

요약·알림(모바일 푸시 등)은 이 시스템 범위 밖 — 별도 컴포넌트가 `output/collected/<ts>/<slug>.new.json` 을 읽어 요약본만 보내면 된다(원문 그대로 재배포 금지).

---

## 6. 어떤 사이트가 자동으로 안 되나

- **로그인 필요(LOGIN_REQUIRED)** — 이번 단계 범위 밖. `register.py` 가 거부. (로그인은 사용자가 한 번 수동으로; `playwright_html` 의 `storage_state_path` 로 재사용은 가능하나 자동 생성은 안 함.)
- **차단(BLOCKED_BOT/IP/GEO)으로 정적·headless 둘 다 실패** — `register.py` 가 거부. 차단 우회는 자동 경로에서 일절 안 함.
- **Cloudflare 챌린지가 강한 사이트(arca.live 등)** — `playwright_html` 의 기본 렌더로는 부족할 수 있음. `handwritten` strategy(`ArcaLiveAdapter` 처럼 playwright-stealth 쓰는 손어댑터)로 감싸서 `register.py --config` 로 등록.
- **데이터가 JS 로딩되는 SPA (목록 또는 글 본문)** — register.py 가 자동으로 시도함: 글 본문이 SPA 면 글페이지를 render+HAR 로 re-probe 해서 (a) 본문을 주는 JSON XHR 이 있으면 `article.fetch_kind:"json"` config, (b) 없으면 `strategy:"playwright_html"` 로 전환. 클릭/스크롤 후에야 뜨는(networkidle 만으론 안 잡히는) 데이터거나 Cloudflare 챌린지가 강하면(arca 등) 손어댑터(`handwritten`).

---

## 7. 코드 맵

```
engine/
  config_schema.py    config JSON 스키마 + validate_config
  transforms.py       닫힌 transform 라이브러리 + apply_chain
  extract_helpers.py  field source 해석(css/attr/json/const/template/concat/class_present) + fallback chain + navigate_json
  config_adapter.py   ConfigAdapter(BaseAdapter) + make_adapter + load_config(_dir)
  recognizers/        알려진 플랫폼 URL 인식 패키지 → config 즉시 생성 (register.py 가 probe 전에 recognize() 호출). auto-discovery — <plat>.py 한 파일 추가만으로 인식기 등록
  strategies/         httpx_html / httpx_json / playwright_html (httpx_html 이 파싱 헬퍼 보유 — playwright_html 재사용)
  digest.py           probe 산출물 → gemini 입력 digest (clean_html 포함)
  base_compat.py      adapters.base 의 BaseAdapter/NoticePost 재노출
generate/
  gemini.py           Gemini REST + 다중 API 키 로테이션
  prompt.py           시스템 지침(포맷 스펙) + few-shot(configs/*.json) + build_user_prompt / build_retry_prompt
  generator.py        generate_config(1-shot) / generate_config_validated(검증+재시도 루프)
  validate.py         validate_built_config — 3층위 실행 검증
scripts/
  probe.py --lite     경량 정찰 (외부/유료/login 만 스킵; headless/replay 는 수행)
  register.py         URL → probe → digest → gemini → config + baseline. --config 로 손작성 config 등록도.
  poll.py             등록된 사이트 폴링 + 깨짐 시 재-probe
  gen_config.py       URL → config 만 (수동/디버그)
  gate_check.py       (개발용) gemini config 재생성 통과율 측정
  demo_config.py      config 검증/실행/원본 산출물과 비교
  verify_m1.py        (개발용) config 기반 어댑터 vs 손어댑터 라이브 비교
configs/              생성/등록된 config + few-shot 예제용 레퍼런스 config (skku_cse_1582.json 등)
```

관련: `docs/config 자동생성 실패 케이스.md`(자동 등록이 실패하는 케이스 분류 + 케이스별 대응 — `.FAILED.json` 났을 때 여기부터), `docs/사이트 어댑터 추가 가이드.md`(손어댑터 추가 워크플로우), `docs/크롤링 지침.md`(안전 운영 §7 = 이 엔진의 정책 적용).
