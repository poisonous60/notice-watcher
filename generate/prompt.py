"""Gemini 프롬프트 구성: 시스템 지침(포맷 스펙) + few-shot 예제 + digest → 프롬프트."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from engine import transform_names

_ROOT = Path(__file__).resolve().parent.parent
_CONFIGS_DIR = _ROOT / "configs"

# few-shot 으로 쓸 예제 config 들 (M1 에서 손으로 작성, 원본 어댑터와 결과 일치 검증됨).
_EXAMPLE_CONFIG_FILES = [
    "skku_cse_1582.json",      # httpx_html, concat, pick:first_matching, 페이지네이션 offset
    "dcinside_endfield.json",  # httpx_html, fallback chain, template, attr+match, notice 처리, polite_sleep 하한
    "endfield_official.json",  # httpx_json, list_path, success_when, unixtime_to_iso, article re_extract
]


def _transforms_doc() -> str:
    return ", ".join(transform_names())


SYSTEM_INSTRUCTION = f"""너는 게시판/공지 사이트 크롤링 엔진의 "config 작성기"다.
입력으로 한 게시판의 정찰(probe) 요약 digest 를 받고, 그 게시판을 크롤링하는 **선언적 config(JSON)** 를 출력한다.
출력은 **오직 config JSON 한 개** — 설명·주석·코드펜스 없이 JSON 객체 그 자체만.

## 엔진이 하는 일
config 는 "무엇을 어떻게 긁을지"만 정한다. polite delay / robots / 차단대응 같은 정책은 엔진이 알아서 한다.
엔진은 strategy 에 따라 정해진 코드 경로로 목록(fetch_list)과 본문(fetch_article)을 수행한다.

## strategy (택1)
- "httpx_html"  : 정적 HTML 게시판. httpx GET → bs4 CSS select 로 행 추출. (digest 의 verdict 가 "정적 HTTP로 충분" 류이고 html_repeating_patterns 가 있으면 보통 이것.)
- "httpx_json"  : JSON API 게시판. httpx GET → JSON 경로로 목록 배열 추출. (digest 의 list_candidates.traffic_json_api_candidates 가 있으면.)
- "playwright_html" : JS 렌더 필요(Cloudflare 등 / SPA). httpx_html 과 같은 필드 + wait_selector. (verdict 가 "JS 실행 필요" 류, 또는 escalation_hint 가 시키면.)
- ⚠ **목록은 정적 HTML 인데 *글 본문 페이지* 만 SPA(정적 HTML 에 본문이 비어있음)** 인 경우: strategy 는 "httpx_html" 그대로 두고, article.fetch_kind:"json" + article.url_template(글 본문 JSON API URL, 글 ID 자리는 {{post_id}}) + article.content:[{{from:"json", path:[...]}}] 로 *본문만* API 에서 받아라. 그런 API 후보(digest 의 article_sample.api_candidates)가 없으면 strategy 를 "playwright_html" 로 (목록·본문 둘 다 렌더, article.wait_selector 로 본문 컨테이너 대기).
※ 로그인 필요(LOGIN_REQUIRED)거나 차단(BLOCKED_*)이면 config 생성하지 말고 그렇게 알 수 있는 최소 config(예: 빈 fields)라도 만들지 말 것 — 대신 strategy 를 정해도 무방하나 본 시스템은 그런 사이트를 자동 등록하지 않는다.

## config 최상위 키
version(int, 1), site(str), board(str — url_template 의 {{board}} 로도 쓰임), strategy,
headers(dict — digest 의 static_ok_request_headers / captured_headers 를 참고해 User-Agent 등 채움),
timeout(number, 기본 15), polite_sleep({{min,max}} — robots crawl_delay 가 명시돼 있으면 그 값 이상으로; 없으면 생략),
list({{...}}), article({{...}}).

## list 키
url_template : 페이지네이션 파라미터를 뺀 깔끔한 목록 URL. {{board}} 치환 가능. 예: "https://x/lists/?id={{board}}"
pagination   : {{kind:"query_param"|"offset"|"none", page_param?, size_param?, offset_param?, page_unit?(int), extra_params_when_paged?:dict}}
               - query_param: 1페이지 포함 page_param=페이지번호, size_param=페이지크기 를 항상 붙임.
               - offset: 2페이지부터만 offset_param=(page-1)*page_unit, size_param=page_unit, extra_params_when_paged 를 붙임.
page_size_max: (선택) 서버가 페이지크기를 cap 하면 그 값.
# httpx_html / playwright_html:
row_selector          : 목록 한 행(= 글 하나)을 가리키는 CSS. digest 의 html_repeating_patterns[].selector 후보 중 *글 목록*인 걸 고른다(head>meta 같은 노이즈 말고).
row_required_selector : (선택) 이 selector 가 행 안에 없으면 그 행은 건너뜀(광고/구분선 제거용).
exclude_selector      : (선택) 이 CSS 에 매칭되는 행 제거(광고).
include_notices       : (선택, 기본 true) 공지 행 포함 여부.
notice_class_absent   : (선택) include_notices=false 일 때, 이 class 가 *없는* 행을 공지로 보고 제거.
wait_selector         : (playwright_html 전용) 이 요소가 나타날 때까지 대기.
# httpx_json:
list_path   : 목록 배열까지의 JSON 경로(키 리스트). 예: ["data","list"] 또는 ["result","articleList"]
item_path   : (선택) 각 배열 원소 안에서 글 dict 위치. 예: ["item"]
type_field, type_allow : (선택) 배열 원소의 type_field 값이 type_allow 안에 있어야 채택. 예: type_field="type", type_allow=["ARTICLE"]
success_when: (선택) payload 수준 성공 체크. {{path:["code"], equals:0}}
# 공통:
fields : 글 한 건에서 뽑을 필드들. **post_id 와 title 은 필수**. (post_id 는 새 글 감지의 키 — 안정적인 정수/문자열 ID 여야 함. 매번 바뀌는 slug 면 안 됨.)
         그 외: url, published_at(ISO8601 로 정규화), author, category, summary, cover_image.
         각 필드 값 = source dict 의 **리스트(fallback chain)** — 앞에서부터 시도해 None 아닌 첫 결과 채택.

## source dict ("from" 별)
- {{from:"css", selector:"...", text:true}}                          : 그 요소의 텍스트(여러 공백 → 한 칸). 기본 text:true.
- {{from:"css", selector:"...", attr:"href"}}                        : 그 요소의 속성값.
- {{from:"css", attr:"href"}}  또는  {{from:"css", selector:":self", attr:"href"}}  : **selector 를 빼거나 ":self" 면 행(row) 요소 자체**의 텍스트/속성. (row_selector 가 `a.vrow` 처럼 반복 행이 곧 링크인 경우 — post_id/url 을 이 행의 href 에서 뽑는다.)
- {{from:"css", selector:"...", html:true}}                          : 그 요소의 HTML 통째(본문 content 에 주로).
- {{from:"css", selector:"...", match:"^정규식$"}}                    : 추출값(text 또는 attr)이 이 정규식에 안 맞으면 그 source 는 실패.
- {{from:"css", selector:"...", pick:"first_matching", match:"...", text:true}} : selector 로 *여러* 요소 중 텍스트가 match 에 맞는 첫 요소.
- {{from:"attr", selector:"...", attr:"..."}}                         : css + attr 필수 의 별칭.
- {{from:"json", path:["a","b",0]}}                                  : JSON 경로(키=문자열, 인덱스=정수). httpx_json 의 fields / article.content 에서.
- {{from:"const", value: <임의값, null 가능>}}                        : 고정값.
- {{from:"template", value:"https://x/view?no={{post_id}}&id={{board}}"}} : {{board}},{{post_id}}, 그리고 같은 행에서 이미 추출된 다른 필드명을 치환.
- {{from:"concat", parts:[ {{const:"["}}, {{field:"category"}}, {{const:"] "}}, {{from:"css", selector:"a.title", text:true}} ]}} : 부분들을 이어붙임. {{field:"이름"}} 은 같은 행에서 *먼저 선언된* 필드를 참조(어떤 부분이라도 None 이면 concat 은 None). → 참조하는 필드를 fields 안에서 더 먼저 선언할 것.
- {{from:"class_present", class:"us-post", negate?:true}}            : (css 행 전용) 그 class 가 있으면 "true" 없으면 "false".
각 source 에 "transform":[["name", args...], ...] 체인을 붙일 수 있다. 추출 raw 값에 순서대로 적용(중간에 None 이면 중단).

## 쓸 수 있는 transform (이 목록 밖은 금지)
{_transforms_doc()}
주요 용법:
- ["urljoin","https://base"]              : 상대 URL → 절대.
- ["regex_extract","[?&]no=(\\\\d+)"]       : 정규식 1번 그룹 추출(없으면 None).
- ["collapse_ws"]                          : 연속 공백 → 한 칸 + 양끝 trim.
- ["strip_brackets"]                       : "[학사]" → "학사".
- ["remove_prefix","No."]                  : 접두어 제거.
- ["replace"," ","T"] , ["append","+09:00"] , ["prepend","..."]
- ["date_only_to_iso","+09:00"]            : "2026-05-11" → "2026-05-11T00:00:00+09:00".
- ["unixtime_to_iso","Z","s"]              : 유닉스초 → ISO(UTC). ms 면 ["unixtime_to_iso","+09:00","ms"].
- ["iso8601",["%Y.%m.%d %H:%M"],"+09:00"]  : strptime 포맷들로 파싱 후 ISO. (tz 인자 선택)
- ["zero_pad",4]                           : "751" → "0751".

## article 키 (본문 fetch)
url_template : (선택) post.url 대신 쓸 본문 URL/엔드포인트. {{post_id}},{{board}} 치환. 예: "https://x/api/bulletin/{{post_id}}"
fetch_kind   : "html" | "json" (기본: list 의 strategy 계열)
success_when : (json) payload 성공 체크
data_path    : (json, 선택) 본문 객체까지의 경로. content/enrich/re_extract 는 이 객체 기준.
content      : source dict 리스트. **반드시 위 "글(본문) 페이지 HTML 샘플" 에서 글 본문이 들어있는 *가장 작은* 컨테이너를 직접 찾아** 그 CSS selector 를 쓴다(사이트 헤더/푸터/사이드바/댓글 영역은 제외). 확신 없으면 후보 2~3개를 fallback chain 으로. HTML 이면 [{{from:"css", selector:"div.write_div", html:true}}, {{from:"css", selector:".article-body", html:true}}, ...]. JSON 이면 [{{from:"json", path:["contentHtml"]}}]. (본문이 100자 미만으로 나오면 selector 가 틀린 것 — 샘플 HTML 을 다시 봐라.)
               ※ digest 에 "글 본문 JSON API 후보"(article_sample.api_candidates)가 있으면 그걸 써라: article.url_template = 후보의 url(거기 박힌 글 ID 숫자를 {{post_id}} 로 치환), article.fetch_kind = "json", article.content = [{{from:"json", path: <후보의 body_field_path 그대로>}}]. 필요하면 후보의 request_headers 중 X-Requested-With / Referer 를 config 최상위 headers 에 추가. 후보가 여러 개면 url_id_match=true · body_looks_html=true 인 걸 우선.
skip_status  : (선택) [401,403] 처럼, 이 상태코드면 본문 비워서 반환(차단 우회 안 함).
enrich       : (선택) {{title:[...], published_at:[...], ...}} — 현재 None/빈 값인 필드만 본문 페이지에서 보강.
re_extract   : (선택, json) true 면 본문 payload(data)에서 list.fields 를 재추출해 None 아닌 값으로 덮어씀(엔드필드처럼 본문 API 가 목록 item 과 같은 형태일 때).

## digest 읽는 법
- escalation_hint (있으면) → **이전 시도가 실패해서 주는 강한 지침. 반드시 따른다** (보통 strategy/article 을 바꾸라는 것).
- verdict / recommended_strategy → strategy 선택의 1차 힌트.
- list_candidates.html_repeating_patterns → row_selector 후보(글 목록인 걸 고른다). href_pattern_guess / sample_url 로 글 URL 형태 파악.
- list_candidates.traffic_json_api_candidates → httpx_json 이면 그 URL 과 응답 구조 참고.
- list_candidates.first_article_url → 본문 URL 패턴 + article.content selector 결정에 참고(article_sample.html 도 보고).
- article_sample.api_candidates (있으면) → 글 본문이 SPA 라서 정적 HTML 에 없을 때 본문을 주는 JSON API 후보. article.url_template/fetch_kind/content 를 이걸로 채운다(위 article 키 설명 참고).
- static_ok_request_headers / captured_headers → headers 에 User-Agent / Referer / Origin 등 채움.
- robots.crawl_delay → 있으면 polite_sleep.min 을 그 값 이상으로.
- hydration (있으면) → SPA. __NEXT_DATA__ 등에 글 목록이 들어 있으면 httpx_html 로 그 페이지를 받아 파싱하는 것보다, 거기 데이터를 쓰는 경로를 찾는 게 나을 수 있음(이 경우는 보통 손으로 짜야 하니 자신 없으면 평범하게 row_selector 로).
- list_html / article_sample.html → 실제 HTML. selector 는 여기서 직접 확인해 정한다.

확신이 안 서면 가장 단순하고 견고한 선택(여러 fallback selector, 안정적인 post_id) 을 한다."""


def _load_examples() -> str:
    blocks = []
    for fn in _EXAMPLE_CONFIG_FILES:
        p = _CONFIGS_DIR / fn
        if not p.exists():
            continue
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        blocks.append(f"### 예제: {cfg.get('site')} ({cfg.get('strategy')})\n```json\n{json.dumps(cfg, ensure_ascii=False, indent=2)}\n```")
    return "\n\n".join(blocks)


def build_user_prompt(digest: dict, *, max_html_chars: int = 120_000) -> str:
    """digest → 사용자 턴 텍스트. 큰 HTML 은 JSON-escape 대신 코드블록으로 따로 제시."""
    d = dict(digest)
    list_html = ((d.pop("list_html", {}) or {}))
    article = ((d.pop("article_sample", {}) or {}))
    api_cands = article.get("api_candidates") or []
    eh = d.pop("escalation_hint", None)  # 위 ⚠ 블록으로만 보여줌(meta JSON 중복 X)
    if eh:
        d["escalation_hint"] = "(위 '⚠ 재시도 지침' 블록 참고)"
    lh = (list_html.get("html") or "")[:max_html_chars]
    ah = (article.get("html") or "")[:max_html_chars]

    meta = json.dumps(d, ensure_ascii=False, indent=2)
    examples = _load_examples()

    eh_block = f"\n## ⚠ 재시도 지침 (이전 시도가 실패함 — 반드시 따를 것)\n{eh}\n" if eh else ""
    api_block = ""
    if api_cands:
        api_block = (
            "\n## ⚡ 글 본문 JSON API 후보 (글 페이지가 SPA 라서 정적 HTML 본문이 비어있음 — 이 API 로 본문을 받아라)\n"
            "```json\n" + json.dumps(api_cands, ensure_ascii=False, indent=2) + "\n```\n"
            "→ article.url_template = 후보 url 의 글 ID 숫자를 {{post_id}} 로 치환한 것, article.fetch_kind=\"json\", "
            "article.content=[{{from:\"json\", path:<후보의 body_field_path 그대로>}}]. 필요하면 후보의 request_headers 중 "
            "X-Requested-With/Referer 를 config 최상위 headers 에 추가. 여러 개면 url_id_match=true·body_looks_html=true 우선.\n"
        )

    return f"""아래는 사용자가 모니터링하고 싶은 게시판의 probe digest 다.
{eh_block}
## digest 메타데이터 (verdict / 후보 / 헤더 / robots / hydration 등)
```json
{meta}
```

## 목록 페이지 HTML (정제됨{', 잘림' if list_html.get('truncated') else ''}; source={list_html.get('source')})
```html
{lh}
```

## 글(본문) 페이지 HTML 샘플 (정제됨{', 잘림' if article.get('truncated') else ''}; url={article.get('url')})
```html
{ah}
```
{api_block}
## 참고용 예제 config (다른 사이트들 — 형식만 참고)
{examples}

---
위 게시판에 대한 config JSON 을 출력하라. **JSON 객체 하나만, 다른 텍스트 없이.**"""


def build_retry_prompt(digest: dict, prev_config: dict, feedback_text: str, *, max_html_chars: int = 120_000) -> str:
    """재시도용: 원래 digest/HTML + 이전 config + 검증 실패 내역 → *수정된* config 요청."""
    base = build_user_prompt(digest, max_html_chars=max_html_chars)
    prev = json.dumps(prev_config, ensure_ascii=False, indent=2)
    return f"""{base}

---
## ⚠ 이전 시도가 검증에 실패했다 — 아래를 보고 *수정된* config 를 출력하라
잘 동작한 부분은 그대로 둬도 된다. **FAIL 로 표시된 것은 반드시 고쳐야 한다.**

### 이전 config
```json
{prev}
```

### 검증 결과 (FAIL=하드 실패=필수 수정, warn=가능하면 수정)
{feedback_text}

### 수정 힌트
- post_id 가 안정적 ID 모양이 아니면(공백 등) — title 을 post_id 로 쓴 게 아닌지 확인. post_id 는 URL/href 안의 숫자 ID 같은 걸 써라.
- published_at ISO8601 파싱 실패 — 날짜 문자열 형식을 먼저 맞춰라. "2026.04.17" 면 `["replace",".","-"]` 후 `["date_only_to_iso","+09:00"]`, 또는 `["iso8601",["%Y.%m.%d"],"+09:00"]`.
- 본문 0자 / <100자 — article.content 의 selector 가 틀린 것. 위 "글 페이지 HTML 샘플" 에서 본문 컨테이너를 다시 찾아라. **글 본문이 정적 HTML 에 통째로 없으면(SPA): (a) digest 의 "글 본문 JSON API 후보"(article_sample.api_candidates)가 있으면 article 을 그 API 로 — fetch_kind:"json" + url_template + content:[{{from:"json", path:<body_field_path>}}]. (b) 없으면 strategy 를 "playwright_html" 로 바꾸고 article.wait_selector(없으면 list.wait_selector)에 본문/목록 컨테이너 CSS selector 를 넣어 렌더 완료를 기다려라.**
- 0건 — row_selector(httpx_html) 또는 list_path(httpx_json) 가 잘못됐다. 위 HTML / list_candidates 를 다시 봐라. SPA 라서 정적 HTML 에 글 목록이 없으면 strategy 를 "playwright_html" 로 바꾸고 list.wait_selector 로 목록이 그려질 때까지 기다려라.

수정된 config JSON 하나만 출력하라. 다른 텍스트 없이."""
