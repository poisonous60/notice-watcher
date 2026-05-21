"""engine.recognizers.ruliweb — Ruliweb board config promotion.

Round-trip ground truth is the N100 snapshot JSON embedded in this test. The
configs are not required to exist in this worktree.
"""
from __future__ import annotations

from pathlib import Path

_IGNORE = {"_recognized_platform", "_source_url", "_note", "_slug_board"}


def _functional(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _IGNORE}


def _mobile_expected() -> dict:
    return {
        "version": 1,
        "site": "bbs.ruliweb.com",
        "board": "1004",
        "strategy": "httpx_html",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://bbs.ruliweb.com/mobile/board/1004/rss",
        },
        "timeout": 15,
        "list": {
            "url_template": "https://bbs.ruliweb.com/mobile/board/{board}/rss",
            "pagination": {"kind": "none"},
            "row_selector": "item",
            "fields": {
                "post_id": [{"from": "css", "selector": "link", "text": True, "match": r"^https?://.+/read/\d+$", "transform": [["regex_extract", r"/read/(\d+)$"]]}],
                "title": [{"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]}],
                "url": [{"from": "css", "selector": "link", "text": True, "transform": [["strip"], ["urljoin", "https://bbs.ruliweb.com"]]}],
                "published_at": [{"from": "css", "selector": "pubDate", "text": True, "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]}],
                "author": [{"from": "css", "selector": "author", "text": True, "transform": [["collapse_ws"]]}],
                "category": [{"from": "css", "selector": "category", "text": True, "transform": [["collapse_ws"]]}],
            },
        },
        "article": {
            "url_template": "https://bbs.ruliweb.com/mobile/board/{board}/read/{post_id}",
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.article_content", "html": True},
                {"from": "css", "selector": "div.view_content", "html": True},
                {"from": "css", "selector": "div.board_view_contents", "html": True},
                {"from": "css", "selector": "div#content", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "h3.title", "text": True, "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]},
                ],
                "published_at": [
                    {"from": "css", "selector": "time", "attr": "datetime"},
                    {"from": "css", "selector": "pubDate", "text": True, "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]},
                ],
            },
        },
    }


def _news_expected() -> dict:
    cfg = _mobile_expected()
    cfg["site"] = "host_bbs-ruliweb-com_news_b596932d"
    cfg["board"] = "1001"
    cfg["headers"] = {
        "User-Agent": cfg["headers"]["User-Agent"],
        "Accept": cfg["headers"]["Accept"],
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }
    cfg["list"] = {
        "url_template": "https://bbs.ruliweb.com/news/board/1001/rss",
        "pagination": {"kind": "none"},
        "row_selector": "channel > item",
        "include_notices": True,
        "fields": {
            "post_id": [{"from": "css", "selector": "link", "text": True, "transform": [["regex_extract", r"/read/(\d+)$"]]}],
            "title": [{"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]}],
            "url": [{"from": "css", "selector": "link", "text": True}],
            "published_at": [{"from": "css", "selector": "pubDate", "text": True, "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]}],
            "author": [{"from": "css", "selector": "author", "text": True, "transform": [["collapse_ws"]]}],
            "category": [{"from": "css", "selector": "category", "text": True, "transform": [["collapse_ws"]]}],
            "summary": [{"from": "css", "selector": "description", "text": True, "transform": [["collapse_ws"]]}],
            "cover_image": [{"from": "css", "selector": "description", "text": True, "transform": [["regex_extract", r'src="([^"]+)"']]}],
        },
    }
    cfg["article"] = {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.view_content", "html": True},
            {"from": "css", "selector": "div.article_content", "html": True},
            {"from": "css", "selector": "div.news_view_contents", "html": True},
            {"from": "css", "selector": "div.view_content_wrap", "html": True},
        ],
        "enrich": {
            "title": [{"from": "css", "selector": "h2.view_title", "text": True, "transform": [["collapse_ws"]]}],
            "published_at": [{"from": "css", "selector": "div.view_info time", "text": True, "transform": [["iso8601", ["%Y.%m.%d %H:%M"], "+09:00"]]}],
        },
    }
    return cfg


def _pc_expected() -> dict:
    cfg = _news_expected()
    cfg["site"] = "bbs.ruliweb.com"
    cfg["board"] = "pc/board/1003"
    cfg["list"] = {
        "url_template": "https://bbs.ruliweb.com/pc/board/1003/rss",
        "pagination": {"kind": "none"},
        "row_selector": "item",
        "fields": {
            "post_id": [{"from": "css", "selector": "link", "text": True, "transform": [["regex_extract", r"/read/(\d+)$"]]}],
            "title": [{"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]}],
            "url": [{"from": "css", "selector": "link", "text": True, "transform": [["strip"], ["html_unescape"]]}],
            "published_at": [{"from": "css", "selector": "pubDate", "text": True, "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]}],
            "author": [{"from": "css", "selector": "author", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]}],
            "category": [{"from": "css", "selector": "category", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]}],
            "summary": [{"from": "css", "selector": "description", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]}],
        },
    }
    cfg["article"] = {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.view_content", "html": True},
            {"from": "css", "selector": "div.article_view", "html": True},
            {"from": "css", "selector": "div.article-content", "html": True},
            {"from": "css", "selector": "article", "html": True},
        ],
        "enrich": {
            "title": [
                {"from": "css", "selector": "h3.title", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]},
                {"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"], ["html_unescape"]]},
            ],
            "published_at": [{"from": "css", "selector": "time, .date, .regdate", "text": True}],
        },
    }
    return cfg


def _ps_expected() -> dict:
    cfg = _mobile_expected()
    cfg["board"] = "300004"
    cfg["headers"]["Referer"] = "https://bbs.ruliweb.com/ps/board/300004"
    cfg["list"] = {
        "url_template": "https://bbs.ruliweb.com/ps/board/{board}",
        "pagination": {"kind": "query_param", "page_param": "page"},
        "row_selector": "table.board_list_table > tbody > tr, div.board_list_table > table > tbody > tr, .board_list_table tbody tr",
        "row_required_selector": "a[href*='/read/']",
        "include_notices": True,
        "fields": {
            "post_id": [{"from": "attr", "selector": "a[href*='/read/']", "attr": "href", "transform": [["regex_extract", r"/read/(\d+)"]]}],
            "title": [{"from": "css", "selector": "a[href*='/read/']", "text": True, "transform": [["collapse_ws"]]}],
            "url": [{"from": "attr", "selector": "a[href*='/read/']", "attr": "href", "transform": [["urljoin", "https://bbs.ruliweb.com"]]}],
            "published_at": [
                {
                    "from": "css",
                    "selector": "time, .time, .date, td",
                    "pick": "first_matching",
                    "match": r"^\d{4}-\d{2}-\d{2}|^\d{4}\.\d{2}\.\d{2}|^\d{2}:\d{2}$",
                    "text": True,
                    "transform": [["collapse_ws"], ["iso8601", ["%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"], "+09:00"]],
                },
                {"from": "css", "selector": "a[href*='/read/'] + span, a[href*='/read/'] ~ span", "text": True, "transform": [["collapse_ws"]]},
            ],
            "author": [{"from": "css", "selector": "a[href*='/read/'] ~ span, .nick, .writer, .author", "pick": "first_matching", "match": r"^.+$", "text": True, "transform": [["collapse_ws"]]}],
            "category": [{"from": "css", "selector": "a[href*='/read/'] ~ span, .subject, .cate, .category", "pick": "first_matching", "match": r"^.+$", "text": True, "transform": [["collapse_ws"]]}],
        },
    }
    cfg["article"] = {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.view_content", "html": True},
            {"from": "css", "selector": "div#view_content", "html": True},
            {"from": "css", "selector": "div.article_content", "html": True},
            {"from": "css", "selector": "div.fr-view", "html": True},
        ],
    }
    return cfg


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject
    from engine.recognizers.ruliweb import PATTERNS, _build

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []
    members = [
        ("mobile", "https://bbs.ruliweb.com/mobile/board/1004/rss", _mobile_expected()),
        ("news", "https://bbs.ruliweb.com/news/board/1001/rss", _news_expected()),
        ("pc", "https://bbs.ruliweb.com/pc/board/1003/rss", _pc_expected()),
        ("ps", "https://bbs.ruliweb.com/ps/board/300004", _ps_expected()),
    ]

    for name, url, expected in members:
        built = _try(url)
        ok = built is not None and _functional(built) == expected
        if not ok and built is not None:
            diffs = [k for k in set(_functional(built)) | set(expected) if _functional(built).get(k) != expected.get(k)]
            detail = f"diff keys {diffs}"
        else:
            detail = f"built={built is not None}"
        cases.append((f"roundtrip[{name}]", ok, detail))

    for name, url, _ in members:
        cfg = recognize(url)
        cases.append((f"recognize[{name}]", cfg is not None and cfg.get("_recognized_platform") == "ruliweb", f"got {cfg and cfg.get('_recognized_platform')!r}"))
        rej = recognize_reject(url)
        cases.append((f"reject_none[{name}]", rej is None, f"got {rej!r}"))

    slug_expect = {
        "https://bbs.ruliweb.com/mobile/board/1004/rss": "mobile_1004",
        "https://bbs.ruliweb.com/news/board/1001/rss": "news_1001",
        "https://bbs.ruliweb.com/pc/board/1003/rss": "pc_1003",
        "https://bbs.ruliweb.com/ps/board/300004": "ps_300004",
    }
    for url, slug in slug_expect.items():
        cfg = _try(url)
        cases.append((f"slug[{slug}]", cfg is not None and cfg.get("_slug_board") == slug, f"got {cfg and cfg.get('_slug_board')!r}"))

    other = recognize("https://example.com/mobile/board/1004/rss")
    cases.append(("other_host_negative", other is None or other.get("_recognized_platform") != "ruliweb", f"got {other and other.get('_recognized_platform')!r}"))

    same_host_neg = [
        "https://bbs.ruliweb.com/mobile/board/1004/read/123456",
        "https://bbs.ruliweb.com/news/board/1001/read/123456",
        "https://bbs.ruliweb.com/pc/board/1003/read/123456",
        "https://bbs.ruliweb.com/ps/board/300004/read/123456",
        "https://bbs.ruliweb.com/community",
        "https://bbs.ruliweb.com/market/board/1020",
        "https://bbs.ruliweb.com/ps/board/300004/rss",
        "https://bbs.ruliweb.com/mobile/board/1004",
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "ruliweb"
        tag = u.split("bbs.ruliweb.com")[1][:28]
        cases.append((f"same_host_neg[{tag}]", not hit, f"recognize→ {r and r.get('_recognized_platform')!r}"))

    return cases


def test_run_protocol() -> None:
    failed = [(n, d) for n, ok, d in run() if not ok]
    assert not failed


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
