"""알려진 플랫폼 인식기 — 새 게시판 URL 이 *이미 손어댑터 / 검증된 config 패턴이 있는* 플랫폼이면
probe + Gemini 없이 config 를 바로 만들어 등록한다. `register.py` 가 probe 전에 `recognize()` 를 호출.

추가 방법: `_RECOGNIZERS` 에 `(name, 컴파일된 정규식, builder(match, url) -> config dict | None)` 를 한 줄 추가.
- 정규식은 URL 전체에 `.search()` 됨 (스킴 무관하게 `//host/...` 부터 매칭하면 됨).
- builder 는 config dict 를 돌려준다(스키마는 `engine.config_schema` 기준). `_source_url`·`_note` 도 채운다.
  잘못 매칭됐을 가능성이 있으면 register.py 가 fetch_list 0건일 때 일반 파이프라인으로 폴백하므로 builder 는 낙관적으로 만들어도 된다.
- `recognize()` 가 첫 매칭 builder 의 결과에 `_recognized_platform: name` 을 붙여 반환.

새 플랫폼을 손어댑터/손config 로 한 번 처리했으면 → 여기에 인식기를 한 줄 추가해서 같은 플랫폼의 다른 게시판은 자동으로 잡히게 한다.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _qs(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items() if v}


# ----------------------------------------------------------------------------
# 네이버 카페 → NaverCafeAdapter(목록/공지/본문 JSON API)
# ----------------------------------------------------------------------------
_NAVER_CAFE_NOTE = ("네이버 카페 — known-platform 자동 인식. 손어댑터 NaverCafeAdapter 가 목록/공지/본문 JSON API"
                    "(apis.naver.com/cafe-web/..., article.cafe.naver.com/gw/...)를 직접 호출. cafe_id/menu_id 는 URL 에서. "
                    "비공개·등급제한 게시판이면 본문 API 가 401/403 → 어댑터가 본문 비워 반환(우회 안 함; storage_state 로그인 필요).")


def _naver_cafe_cfg(cafe_id: int, menu_id: int, url: str) -> dict:
    return {
        "version": 1, "site": "cafe.naver.com", "board": f"cafe{cafe_id}/menu{menu_id}",
        "strategy": "handwritten", "adapter": "NaverCafeAdapter",
        "kwargs": {"cafe_id": int(cafe_id), "menu_id": int(menu_id), "include_notices": True, "timeout": 15.0},
        "_source_url": url, "_note": _NAVER_CAFE_NOTE,
    }


# https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L  (신 UI 메뉴 URL)
def _b_naver_cafe_menu(m: "re.Match", url: str) -> Optional[dict]:
    return _naver_cafe_cfg(int(m.group(1)), int(m.group(2)), url)


# https://cafe.naver.com/f-e/cafes/30291108/articles/12345?menuid=6&...  (신 UI 글 URL — menuid 가 쿼리에)
def _b_naver_cafe_article(m: "re.Match", url: str) -> Optional[dict]:
    # menuid 쿼리가 잘려서 없으면 어느 메뉴인지 알 수 없으니 None → 일반 파이프라인으로 폴백(그쪽도 네이버 카페면 실패하지만 안전).
    menu_id = _qs(url).get("menuid") or _qs(url).get("menuId")
    if not (menu_id and str(menu_id).isdigit()):
        return None
    return _naver_cafe_cfg(int(m.group(1)), int(menu_id), url)


# https://cafe.naver.com/ArticleList.nhn?search.clubid=30291108&search.menuid=6  (구 UI)
def _b_naver_cafe_legacy(m: "re.Match", url: str) -> Optional[dict]:
    q = _qs(url)
    club = q.get("search.clubid") or q.get("clubid")
    menu = q.get("search.menuid") or q.get("menuid")
    if not (club and menu and str(club).isdigit() and str(menu).isdigit()):
        return None
    return _naver_cafe_cfg(int(club), int(menu), url)


# ----------------------------------------------------------------------------
# 다음 카페 모바일 → DaumCafeAdapter (페이지 인라인 JS `articles.push({...})` 파싱)
# ----------------------------------------------------------------------------
_DAUM_RESERVED = {"_c21_", "_rec", "bbs_list", "articles", "search", "info", "join", "memo", "popular"}


def _b_daum_cafe(m: "re.Match", url: str) -> Optional[dict]:
    cafe_name = m.group(1)
    board = m.group(2)
    if board in _DAUM_RESERVED:
        # 레거시 PC URL: cafe.daum.net/<cafe>/_c21_/bbs_list?grpid=...&fldid=Z4os 면 fldid 를 board 로.
        if board == "_c21_":
            fldid = _qs(url).get("fldid")
            if not fldid:
                return None
            board = fldid
        else:
            return None
    # 의도: PC URL(cafe.daum.net/...)이든 모바일 URL(m.cafe.daum.net/...)이든 모두 모바일 어댑터(DaumCafeAdapter,
    # 내부적으로 m.cafe.daum.net 만 fetch)로 정규화한다 → config 의 site 도 항상 "m.cafe.daum.net". slug 만 사용자가 준
    # URL 기준(register.py 가 _source_url 을 그 url 로 덮어씀) — 봇 _is_registered 가 그 slug 로 찾으므로 일관됨.
    return {
        "version": 1, "site": "m.cafe.daum.net", "board": board,
        "strategy": "handwritten", "adapter": "DaumCafeAdapter",
        "kwargs": {"cafe_name": cafe_name, "board_id": board},
        "_source_url": url,
        "_note": ("다음카페 모바일 — known-platform 자동 인식. 글 목록이 페이지 인라인 JS(var articles=[]; articles.push({...}))로만 와서 "
                  "손어댑터 DaumCafeAdapter 가 그 블록을 regex 파싱 + 본문(div#article) fetch. 비공개·등급제한이면 본문 401/403 → 본문 비워 반환(우회 안 함)."),
    }


# ----------------------------------------------------------------------------
# 아카라이브 채널 → ArcaLiveAdapter (playwright-stealth, Cloudflare 통과)
# ----------------------------------------------------------------------------
def _b_arca(m: "re.Match", url: str) -> Optional[dict]:
    channel = m.group(1)
    return {
        "version": 1, "site": "arca.live", "board": channel,
        "strategy": "handwritten", "adapter": "ArcaLiveAdapter",
        "kwargs": {"channel": channel, "include_notices": True},
        "_source_url": f"https://arca.live/b/{channel}",
        "_note": ("아카라이브 — known-platform 자동 인식. Cloudflare 보호 + JS 렌더라 손어댑터 ArcaLiveAdapter(playwright-stealth) 사용. "
                  "특정 카테고리 탭만 받고 싶으면 kwargs 에 category 추가."),
    }


# ----------------------------------------------------------------------------
# 디시인사이드 미니갤러리 → DCInsideMGalleryAdapter
# ----------------------------------------------------------------------------
def _b_dcinside_mgallery(m: "re.Match", url: str) -> Optional[dict]:
    gallery_id = _qs(url).get("id")
    if not gallery_id:
        return None
    return {
        "version": 1, "site": "dcinside.mgallery", "board": gallery_id,
        "strategy": "handwritten", "adapter": "DCInsideMGalleryAdapter",
        "kwargs": {"gallery_id": gallery_id, "include_notices": True},
        "_source_url": f"https://gall.dcinside.com/mgallery/board/lists/?id={gallery_id}",
        "_note": "디시인사이드 미니갤 — known-platform 자동 인식. 손어댑터 DCInsideMGalleryAdapter. robots Crawl-Delay 30 준수(폴링 느림).",
    }


# ----------------------------------------------------------------------------
# 넥슨 포럼 → httpx_json (공개 API: /api/v1/board/{board}/threads, /api/v1/thread/{id})
# ----------------------------------------------------------------------------
def _b_nexon_forum(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1)
    board = _qs(url).get("board")
    if not (board and str(board).isdigit()):
        return None
    view_url = f"https://forum.nexon.com/{game}/board_list?board={board}"
    return {
        "version": 1, "site": "forum.nexon.com", "board": str(board), "strategy": "httpx_json",
        "_source_url": view_url,
        "_note": (f"넥슨 포럼({game}) — known-platform 자동 인식. 목록=/api/v1/board/{{board}}/threads?alias={game}, "
                  f"본문=/api/v1/thread/{{threadId}}?alias={game}. createDate=unix epoch(초), title/summary 는 HTML 이스케이프됨."),
        "headers": {
            "User-Agent": _UA, "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9", "X-Requested-With": "XMLHttpRequest", "Referer": view_url,
        },
        "timeout": 15.0,
        "list": {
            "url_template": f"https://forum.nexon.com/api/v1/board/{{board}}/threads?alias={game}&paginationType=PAGING&pageSize=30&blockSize=5&hideType=WEB",
            "pagination": {"kind": "query_param", "page_param": "pageNo"},
            "list_path": ["threads"],
            "fields": {
                "post_id": [{"from": "json", "path": ["threadId"]}],
                "title": [{"from": "json", "path": ["title"], "transform": [["html_unescape"], ["collapse_ws"]]}],
                "url": [{"from": "template", "value": f"https://forum.nexon.com/{game}/board_view?board={{board}}&thread={{post_id}}"}],
                "published_at": [{"from": "json", "path": ["createDate"], "transform": [["unixtime_to_iso", "+09:00", "s"]]}],
                "author": [{"from": "json", "path": ["user", "nickname"]}],
                "summary": [{"from": "json", "path": ["summary"], "transform": [["html_unescape"], ["collapse_ws"]]}],
                "cover_image": [{"from": "json", "path": ["thumbnailImageUrl"]}],
            },
        },
        "article": {
            "url_template": f"https://forum.nexon.com/api/v1/thread/{{post_id}}?alias={game}",
            "fetch_kind": "json", "content": [{"from": "json", "path": ["content"]}], "re_extract": True,
        },
    }


# ----------------------------------------------------------------------------
# 네이버 게임 라운지 → httpx_json (내부 API: comm-api.game.naver.com/.../feed)
# ----------------------------------------------------------------------------
def _b_naver_game_lounge(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1)
    board_id = m.group(2)
    base = f"https://comm-api.game.naver.com/nng_main/v1/community/lounge/{game}"
    view_url = f"https://game.naver.com/lounge/{game}/board/{board_id}"
    return {
        "version": 1, "site": "game.naver.com", "board": f"lounge/{game}/{board_id}", "strategy": "httpx_json",
        "headers": {
            "User-Agent": _UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "ko-KR,ko;q=0.9",
            "Origin": "https://game.naver.com", "Referer": view_url,
            "front-client-platform-type": "PC", "front-client-product-type": "web",
        },
        "timeout": 15.0,
        "list": {
            "url_template": f"{base}/feed?boardId={board_id}&buffFilteringYN=N&limit=25&offset=0&order=NEW",
            "pagination": {"kind": "offset", "offset_param": "offset", "size_param": "limit", "page_unit": 25},
            "success_when": {"path": ["code"], "equals": 200},
            "list_path": ["content", "feeds"],
            "fields": {
                "post_id": [{"from": "json", "path": ["feed", "feedId"]}],
                "title": [{"from": "json", "path": ["feed", "title"]}],
                "url": [{"from": "json", "path": ["feedLink", "pc"]},
                        {"from": "template", "value": f"https://game.naver.com/lounge/{game}/board/detail/{{post_id}}"}],
                "published_at": [{"from": "json", "path": ["feed", "createdDate"], "transform": [["iso8601", ["%Y%m%d%H%M%S"], "+09:00"]]}],
                "author": [{"from": "json", "path": ["user", "nickname"]}],
                "category": [{"from": "json", "path": ["board", "boardName"]}],
                "cover_image": [{"from": "json", "path": ["feed", "repImageUrl"]}],
            },
        },
        "article": {
            "url_template": f"{base}/feed/{{post_id}}", "fetch_kind": "json",
            "success_when": {"path": ["code"], "equals": 200}, "data_path": ["content"],
            "content": [{"from": "json", "path": ["feed", "contents"]}],
        },
        "_source_url": view_url,
        "_note": (f"네이버 게임 라운지({game} board {board_id}) — known-platform 자동 인식. 목록 comm-api.game.naver.com/.../feed?boardId={board_id}&order=NEW "
                  "(offset 페이징, success code==200, list_path content.feeds, 엔트리 안에 feed/user/feedLink/board 서브객체), 본문 .../feed/{feedId} → content.feed.contents. "
                  "헤더는 UA + front-client-platform-type:PC + front-client-product-type:web + Referer/Origin."),
    }


# ----------------------------------------------------------------------------
# Reddit 서브레딧 → RedditAdapter (공개 .json 엔드포인트)
# ----------------------------------------------------------------------------
_REDDIT_SORTS = {"hot", "new", "top", "rising"}
_REDDIT_TIMES = {"hour", "day", "week", "month", "year", "all"}
_REDDIT_NOT_SUB = {"comments", "wiki", "about", "submit", "search"}


def _b_reddit(m: "re.Match", url: str) -> Optional[dict]:
    sub = m.group(1)
    if not sub or sub.lower() in _REDDIT_NOT_SUB:
        return None
    path = urlsplit(url).path or ""
    needle = "/r/" + sub.lower()
    i = path.lower().find(needle)
    rest = path[i + len(needle):].strip("/") if i != -1 else ""
    first = rest.split("/", 1)[0].lower() if rest else ""
    if first == "comments":
        return None  # 단일 글 URL — 게시판 워처 대상 아님 → 일반 파이프라인으로 폴백(거기서 실패하면 triage)
    sort = first if first in _REDDIT_SORTS else "new"
    q = _qs(url)
    time_filter = q.get("t") if (sort == "top" and q.get("t") in _REDDIT_TIMES) else "day"
    flair = None
    fm = re.search(r'flair_name:\s*"?([^"&]+)"?', q.get("f") or "", re.I)
    if fm:
        flair = fm.group(1).strip() or None

    kwargs: dict = {"subreddit": sub}
    if sort != "new":
        kwargs["sort"] = sort
        if sort == "top":
            kwargs["time_filter"] = time_filter
    if flair:
        kwargs["flair"] = flair

    board_parts = [sub]
    if sort != "new":
        board_parts.append(sort + (f":{time_filter}" if sort == "top" else ""))
    if flair:
        board_parts.append(f"flair={flair}")
    sort_seg = "" if sort == "new" else f"/{sort}"
    src = f"https://www.reddit.com/r/{sub}{sort_seg}/" + (f"?t={time_filter}" if sort == "top" else "")
    return {
        "version": 1, "site": "reddit.com", "board": "/".join(board_parts),
        "strategy": "handwritten", "adapter": "RedditAdapter", "kwargs": kwargs,
        "_source_url": src,
        "_note": ("Reddit 서브레딧 — known-platform 자동 인식. 손어댑터 RedditAdapter 가 공개 .json 엔드포인트"
                  "(목록 /r/{sub}/{sort}.json, 본문 permalink+/.json) 사용. 기본 sort=new(새 글 전부); URL 이 /r/X/hot/ 또는 /top/?t=day 면 그 정렬, "
                  "?f=flair_name:\"...\" 면 그 플레어 글만(창작/공식소식 탭 효과). 자동 인식되면 sort/flair 외의 옵션은 "
                  "configs/<slug>.json 을 직접 손봐서(kwargs.include_stickied 등) register.py --config 로 재등록. "
                  "robots.txt 는 Disallow:/ 라 회색지대 — 저빈도 개인용·UA+polite_sleep·우회 없음."),
    }


# ----------------------------------------------------------------------------
# 레지스트리 (위에서부터 첫 매칭 채택)
# ----------------------------------------------------------------------------
_RECOGNIZERS: list[tuple[str, "re.Pattern", Callable[["re.Match", str], Optional[dict]]]] = [
    ("naver-cafe", re.compile(r"//(?:m\.)?cafe\.naver\.com/[A-Za-z0-9_-]+/cafes/(\d+)/menus/(\d+)\b", re.I), _b_naver_cafe_menu),
    ("naver-cafe", re.compile(r"//(?:m\.)?cafe\.naver\.com/[A-Za-z0-9_-]+/cafes/(\d+)/articles/\d+\b", re.I), _b_naver_cafe_article),
    ("naver-cafe", re.compile(r"//(?:m\.)?cafe\.naver\.com/ArticleList\.nhn\b", re.I), _b_naver_cafe_legacy),
    ("daum-cafe", re.compile(r"//(?:m\.)?cafe\.daum\.net/([^/?#]+)/([^/?#]+)(?:[/?#]|$)", re.I), _b_daum_cafe),
    ("arca-live", re.compile(r"//arca\.live/b/([^/?#]+)", re.I), _b_arca),
    ("dcinside-mgallery", re.compile(r"//gall\.dcinside\.com/mgallery/board/(?:lists|view)/?\?", re.I), _b_dcinside_mgallery),
    ("nexon-forum", re.compile(r"//forum\.nexon\.com/([^/?#]+)/board_(?:list|view)\b", re.I), _b_nexon_forum),
    ("naver-game-lounge", re.compile(r"//game\.naver\.com/lounge/([^/?#]+)/board/(\d+)\b", re.I), _b_naver_game_lounge),
    ("reddit", re.compile(r"//(?:www\.|old\.|new\.|np\.|m\.|i\.)?reddit\.com/r/([A-Za-z0-9_]+)", re.I), _b_reddit),
]


def recognize(url: str) -> Optional[dict]:
    """url 이 알려진 플랫폼이면 그 config dict (`_recognized_platform` 키 포함), 아니면 None."""
    if not url:
        return None
    for name, pat, builder in _RECOGNIZERS:
        m = pat.search(url)
        if not m:
            continue
        try:
            cfg = builder(m, url)
        except Exception:  # noqa: BLE001  builder 가 터지면 그 인식기는 건너뜀(폴백) — 단 단서는 남긴다
            log.debug("known_platforms: builder %r 예외 (url=%r)", name, url, exc_info=True)
            cfg = None
        if not cfg:
            continue
        cfg["_recognized_platform"] = name
        return cfg
    return None


def platform_names() -> list[str]:
    return list(dict.fromkeys(name for name, _, _ in _RECOGNIZERS))
