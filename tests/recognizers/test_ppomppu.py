"""engine.recognizers.ppomppu — Ppomppu zboard httpx_html config."""
from __future__ import annotations

from pathlib import Path

_IGNORE = {"_recognized_platform", "_source_url", "_note", "_slug_board"}


def _functional(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _IGNORE}


def _expected(board: str, *, divpage: str | None = None, phone: bool = False) -> dict:
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    source_url = f"https://www.ppomppu.co.kr/zboard/zboard.php?id={board}"
    if divpage:
        source_url += f"&divpage={divpage}"

    fields = {
        "post_id": [{
            "from": "attr", "selector": "a.baseList-title", "attr": "href",
            "transform": [["regex_extract", "[?&]no=(\\d+)"]],
        }],
        "title": [{
            "from": "css", "selector": "a.baseList-title", "text": True,
            "transform": [["collapse_ws"]],
        }],
        "url": [{
            "from": "attr", "selector": "a.baseList-title", "attr": "href",
            "transform": [["urljoin", "https://www.ppomppu.co.kr/zboard/"]],
        }],
        "published_at": [
            {
                "from": "css", "selector": "td.baseList-time", "attr": "title",
                "match": "^\\d{2}\\.\\d{2}\\.\\d{2} \\d{2}:\\d{2}:\\d{2}$",
                "transform": [["iso8601", ["%y.%m.%d %H:%M:%S"], "+09:00"]],
            },
            {
                "from": "css", "selector": "td.baseList-time", "text": True,
                "match": "^\\d{2}/\\d{2}/\\d{2}$",
                "transform": [["iso8601", ["%y/%m/%d"], "+09:00"]],
            },
        ],
        "author": [{
            "from": "css", "selector": "a.baseList-name span.baseList-name", "text": True,
            "transform": [["collapse_ws"]],
        }],
        "summary": [{
            "from": "css", "selector": "a.baseList-title", "text": True,
            "transform": [["collapse_ws"]],
        }],
    }
    if phone:
        fields["post_id"][0]["transform"] = [
            ["urljoin", "https://www.ppomppu.co.kr/zboard/"],
            ["regex_extract", "[?&]no=(\\d+)"],
        ]
        fields["published_at"] = [
            {
                "from": "attr", "selector": "td[title]", "attr": "title",
                "match": "^\\d{2}\\.\\d{2}\\.\\d{2} \\d{2}:\\d{2}:\\d{2}$",
                "transform": [["iso8601", ["%y.%m.%d %H:%M:%S"], "+09:00"]],
            },
            {
                "from": "css", "selector": "time.baseList-time", "text": True,
                "match": "^\\d{2}/\\d{2}/\\d{2}$",
                "transform": [["iso8601", ["%y/%m/%d"], "+09:00"]],
            },
            {
                "from": "css", "selector": "time.baseList-time", "text": True,
                "match": "^\\d{2}:\\d{2}:\\d{2}$",
            },
        ]
        fields["author"] = [{
            "from": "css", "selector": "a.baseList-name, .list_name .baseList-name", "text": True,
            "transform": [["collapse_ws"]],
        }]
        fields.pop("summary")
        fields["category"] = [
            {"from": "css", "selector": "#topNotice span#notice-icon", "text": True, "transform": [["collapse_ws"]]},
            {"from": "css", "selector": "#topNotice span#alert-icon", "text": True, "transform": [["collapse_ws"]]},
            {"from": "css", "selector": "#topNotice span#ad-icon", "text": True, "transform": [["collapse_ws"]]},
        ]

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": source_url,
    }
    if phone:
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-CH-UA": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": "\"Windows\"",
            "Referer": source_url,
        }

    list_cfg = {
        "url_template": "https://www.ppomppu.co.kr/zboard/zboard.php?id={board}" + (f"&divpage={divpage}" if divpage else ""),
        "pagination": {"kind": "query_param", "page_param": "page", "size_param": "page_num"},
        "page_size_max": 30,
        "row_selector": "#revolution_main_table tr.baseList",
        "include_notices": True,
        "fields": fields,
    }
    if phone:
        list_cfg.pop("page_size_max")
        list_cfg["pagination"] = {"kind": "query_param", "page_param": "page"}
        list_cfg["row_required_selector"] = "a.baseList-title"

    article = {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.JS_ContentMain td.board-contents", "html": True},
            {"from": "css", "selector": "td.board-contents", "html": True},
        ],
        "enrich": {
            "title": [{
                "from": "css", "selector": "#topTitle h1", "text": True,
                "transform": [["collapse_ws"]],
            }],
            "published_at": [{
                "from": "css",
                "selector": "div.topTitle-box > ul.topTitle-mainbox > li",
                "pick": "first_matching",
                "match": "^등록일\\s+\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}$",
                "text": True,
                "transform": [
                    ["regex_extract", "등록일\\s+(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2})"],
                    ["replace", " ", "T"],
                    ["append", ":00+09:00"],
                ],
            }],
        },
    }
    if phone:
        article["url_template"] = "https://www.ppomppu.co.kr/zboard/view.php?id={board}&no={post_id}"
        article["content"] = [
            {"from": "css", "selector": "td.board-contents", "html": True},
            {"from": "css", "selector": "div.JS_ContentMain td.board-contents", "html": True},
            {"from": "css", "selector": "div.JS_ContentMain .board-contents", "html": True},
        ]
        article["enrich"]["published_at"][0]["selector"] = "#topTitle li"

    return {
        "version": 1,
        "site": "ppomppu.co.kr" if phone else "www.ppomppu.co.kr",
        "board": board,
        "strategy": "httpx_html",
        "headers": headers,
        "timeout": 15,
        "list": list_cfg,
        "article": article,
    }


GROUND_TRUTH = {
    "https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu": _expected("ppomppu"),
    "https://www.ppomppu.co.kr/zboard/zboard.php?id=computer&divpage=133": _expected("computer", divpage="133"),
    "https://www.ppomppu.co.kr/zboard/zboard.php?id=phone": _expected("phone", phone=True),
}


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.ppomppu import _build, PATTERNS
    from engine.recognizers import recognize, recognize_reject

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    # 1) URL query id → board/_slug_board/list template.
    cfg = _try("https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu")
    cases.append(("extract_board",
                  cfg is not None
                  and cfg.get("board") == "ppomppu"
                  and cfg.get("_slug_board") == "zboard_ppomppu"
                  and cfg["list"]["url_template"] == "https://www.ppomppu.co.kr/zboard/zboard.php?id={board}",
                  f"board={cfg and cfg.get('board')!r} slug={cfg and cfg.get('_slug_board')!r}"))

    # 2) divpage query is preserved when present in the member URL.
    cfg = _try("https://www.ppomppu.co.kr/zboard/zboard.php?id=computer&divpage=133")
    cases.append(("divpage_preserved",
                  cfg is not None
                  and cfg["headers"]["Referer"].endswith("id=computer&divpage=133")
                  and cfg["list"]["url_template"].endswith("id={board}&divpage=133"),
                  f"referer={cfg and cfg['headers'].get('Referer')!r}"))

    # 3) round-trip: embedded N100 snapshot configs are reproduced on functional fields.
    repro_ok, detail = True, []
    for url, existing in GROUND_TRUTH.items():
        built = _try(url)
        if built is None:
            repro_ok = False
            detail.append(f"{url}: builder None")
            continue
        if _functional(built) != _functional(existing):
            repro_ok = False
            diffs = [k for k in set(_functional(built)) | set(_functional(existing))
                     if _functional(built).get(k) != _functional(existing).get(k)]
            detail.append(f"{url}: diff keys {diffs}")
    cases.append(("roundtrip_embedded_snapshot", repro_ok,
                  f"{len(GROUND_TRUTH)}건 비교 · " + ("; ".join(detail) or "all reproduced")))

    # 4) recognize() integration.
    cfg = recognize("https://www.ppomppu.co.kr/zboard/zboard.php?id=phone")
    cases.append(("recognize_integration",
                  cfg is not None and cfg.get("_recognized_platform") == "ppomppu",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    # 5) other-host negative.
    cfg = recognize("https://example.com/zboard/zboard.php?id=ppomppu")
    cases.append(("other_host_negative",
                  cfg is None or cfg.get("_recognized_platform") != "ppomppu",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    # 6) same-host different-kind negative: article, root, and alternate zboard pages are not board lists.
    same_host_neg = [
        "https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=123456",
        "https://www.ppomppu.co.kr/",
        "https://www.ppomppu.co.kr/zboard/zboard.php",
        "https://www.ppomppu.co.kr/zboard/zboard.php?category=1",
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "ppomppu"
        tag = u.split("ppomppu.co.kr")[1][:28] or "/"
        cases.append((f"same_host_neg[{tag}]", not hit,
                      f"recognize→ {r and r.get('_recognized_platform')!r} (None/타platform 이어야)"))

    # 7) reject fast-path must not block the member board URLs.
    for u in GROUND_TRUTH:
        out = recognize_reject(u)
        cases.append((f"reject_none[{u.split('id=')[1]}]", out is None, f"got {out!r}"))

    return cases


def test_ppomppu_recognizer() -> None:
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
