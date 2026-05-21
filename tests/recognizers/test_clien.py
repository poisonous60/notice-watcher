"""engine.recognizers.clien — Clien board httpx_html config.

round-trip 기준은 N100 snapshot 에서 전달된 clien config 4건(lecture/park/news/use)의
기능 필드다. repo 에 git-tracked clien config 는 없으므로 이 파일에 ground-truth 를 embed 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

_IGNORE = {"_recognized_platform", "_source_url", "_note", "_slug_board"}

_GROUND_TRUTH = {
    "https://www.clien.net/service/board/lecture": r'''{
  "version": 1,
  "site": "www.clien.net",
  "board": "lecture",
  "strategy": "httpx_html",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.clien.net/service/board/lecture"
  },
  "timeout": 15,
  "list": {
    "url_template": "https://www.clien.net/service/board/{board}",
    "pagination": {"kind": "query_param", "page_param": "po"},
    "include_notices": true,
    "row_selector": "div.list_content > div.list_item.symph_row",
    "row_required_selector": "a.list_subject[href*='/service/board/lecture/']",
    "exclude_selector": "div.list_item.blocked",
    "fields": {
      "post_id": [
        {"from": "attr", "selector": ":self", "attr": "data-board-sn"},
        {"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["regex_extract", "/service/board/lecture/(\\d+)"]]}
      ],
      "title": [
        {"from": "css", "selector": "span.subject_fixed", "text": true, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "a.list_subject", "text": true, "transform": [["collapse_ws"]]}
      ],
      "url": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["urljoin", "https://www.clien.net"]]}],
      "published_at": [
        {"from": "css", "selector": "span.timestamp", "text": true, "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]},
        {"from": "css", "selector": "div.list_time .time.popover", "text": true, "transform": [["collapse_ws"], ["iso8601", ["%m-%d %H:%M:%S"], "+09:00"]]}
      ],
      "author": [
        {"from": "css", "selector": "div.list_author span.nickname span[title]", "attr": "title"},
        {"from": "css", "selector": "div.list_author span.nickname", "text": true, "transform": [["collapse_ws"]]}
      ],
      "category": [
        {"from": "css", "selector": "span.category.fixed", "attr": "title"},
        {"from": "css", "selector": "span.category.fixed", "text": true, "transform": [["collapse_ws"]]}
      ],
      "summary": [{"from": "css", "selector": "a.list_subject span.subject_fixed", "text": true, "transform": [["collapse_ws"]]}]
    }
  },
  "article": {
    "url_template": "https://www.clien.net/service/board/{board}/{post_id}?od=T31&po=0&category=0&groupCd=",
    "fetch_kind": "html",
    "content": [
      {"from": "css", "selector": "div.post_content div.post_article", "html": true},
      {"from": "css", "selector": "div.post_content article", "html": true},
      {"from": "css", "selector": "div.content_view div.post_view", "html": true}
    ],
    "enrich": {
      "title": [
        {"from": "css", "selector": "h3.post_subject span:last-child", "text": true, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "input#subject", "attr": "value"}
      ],
      "published_at": [{"from": "css", "selector": "div.post_author span.view_count.date", "text": true, "transform": [["collapse_ws"], ["regex_extract", "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})"], ["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}],
      "author": [
        {"from": "css", "selector": "div.post_info div.nickname span[title]", "attr": "title"},
        {"from": "css", "selector": "input#writer", "attr": "value"}
      ]
    }
  }
}''',
    "https://www.clien.net/service/board/park": r'''{
  "version": 1,
  "site": "clien.net",
  "board": "park",
  "strategy": "httpx_html",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.clien.net/service/board/park"
  },
  "timeout": 15,
  "list": {
    "url_template": "https://www.clien.net/service/board/{board}",
    "pagination": {"kind": "query_param", "page_param": "po"},
    "row_selector": "div.list_content > div.list_item.symph_row",
    "row_required_selector": "a.list_subject[href*='/service/board/park/']",
    "exclude_selector": "div.list_item.hongbo",
    "include_notices": true,
    "fields": {
      "post_id": [{"from": "attr", "selector": ":self", "attr": "data-board-sn"}],
      "title": [
        {"from": "css", "selector": "span.subject_fixed", "text": true, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "a.list_subject", "text": true, "transform": [["collapse_ws"]]}
      ],
      "url": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["urljoin", "https://www.clien.net"]]}],
      "published_at": [{"from": "css", "selector": "span.timestamp", "text": true, "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}],
      "author": [
        {"from": "css", "selector": "div.list_author span.nickname span[title]", "attr": "title", "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "div.list_author span.nickname", "text": true, "transform": [["collapse_ws"]]}
      ],
      "summary": [{"from": "css", "selector": "div.list_title span.subject_fixed", "text": true, "transform": [["collapse_ws"]]}]
    }
  },
  "article": {
    "fetch_kind": "html",
    "content": [
      {"from": "css", "selector": "div.post_view div.post_article", "html": true},
      {"from": "css", "selector": "div.post_view article", "html": true}
    ],
    "enrich": {
      "title": [{"from": "css", "selector": "h3.post_subject span", "text": true, "transform": [["collapse_ws"]]}],
      "published_at": [{"from": "css", "selector": "div.post_author span.view_count.date", "text": true, "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}]
    }
  }
}''',
    "https://www.clien.net/service/board/news?od=T31&category=0&groupCd=": r'''{
  "version": 1,
  "site": "clien.net",
  "board": "news",
  "strategy": "httpx_html",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchanged;v=b3;q=0.7",
    "Accept-Language": "ko-KR",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.clien.net/service/board/news"
  },
  "timeout": 15,
  "list": {
    "url_template": "https://www.clien.net/service/board/news?od=T31&category=0&groupCd=",
    "pagination": {"kind": "offset", "offset_param": "po", "page_unit": 1, "extra_params_when_paged": {"od": "T31", "category": "0", "groupCd": ""}},
    "row_selector": "div.list_content > div.list_item.notice, div.list_content > div.list_item.symph_row",
    "row_required_selector": "a.list_subject",
    "include_notices": true,
    "fields": {
      "post_id": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["regex_extract", "/service/board/news/(\\d+)"]]}],
      "title": [
        {"from": "css", "selector": "a.list_subject > span.subject_fixed", "text": true, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "a.list_subject", "text": true, "transform": [["collapse_ws"]]}
      ],
      "url": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["urljoin", "https://www.clien.net"]]}],
      "published_at": [
        {"from": "css", "selector": "span.timestamp", "text": true, "match": "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$", "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]},
        {"from": "css", "selector": "div.list_time span.time.popover", "text": true, "transform": [["collapse_ws"], ["regex_extract", "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})"], ["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}
      ],
      "author": [
        {"from": "css", "selector": "div.list_author span.nickname span[title]", "attr": "title", "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "div.list_author span.nickname", "text": true, "transform": [["collapse_ws"]]}
      ]
    }
  },
  "article": {
    "fetch_kind": "html",
    "content": [
      {"from": "css", "selector": "div.post_view div.post_content div.post_article", "html": true},
      {"from": "css", "selector": "div.post_view article div.post_article", "html": true},
      {"from": "css", "selector": "div.post_view .post_content", "html": true}
    ],
    "enrich": {
      "title": [
        {"from": "css", "selector": "div.post_title h3.post_subject > span", "text": true, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "input#subject", "attr": "value", "transform": [["collapse_ws"]]}
      ],
      "published_at": [{"from": "css", "selector": "div.post_author span.view_count.date", "text": true, "transform": [["collapse_ws"], ["regex_extract", "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})"], ["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}],
      "author": [
        {"from": "css", "selector": "div.post_info span.nickname span[title]", "attr": "title", "transform": [["collapse_ws"]]},
        {"from": "css", "selector": "input#writer", "attr": "value", "transform": [["collapse_ws"]]}
      ]
    }
  }
}''',
    "https://www.clien.net/service/board/use?od=T31&category=0&groupCd=": r'''{
  "version": 1,
  "site": "clien.net",
  "board": "use",
  "strategy": "httpx_html",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.clien.net/service/board/use"
  },
  "timeout": 15,
  "list": {
    "url_template": "https://www.clien.net/service/board/use?od=T31&category=0&groupCd=",
    "pagination": {"kind": "query_param", "page_param": "po"},
    "row_selector": "div.list_content > div.list_item.symph_row[data-role='list-row']",
    "row_required_selector": "a.list_subject",
    "include_notices": false,
    "fields": {
      "post_id": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["regex_extract", "/service/board/use/(\\d+)"]]}],
      "title": [{"from": "css", "selector": "span.subject_fixed", "text": true, "transform": [["collapse_ws"]]}],
      "url": [{"from": "attr", "selector": "a.list_subject", "attr": "href", "transform": [["urljoin", "https://www.clien.net"]]}],
      "category": [{"from": "css", "selector": "span.category.fixed", "text": true, "transform": [["collapse_ws"], ["strip"]]}],
      "author": [{"from": "attr", "selector": "div.list_author .nickname span[title]", "attr": "title", "transform": [["collapse_ws"]]}],
      "published_at": [{"from": "css", "selector": "span.timestamp", "text": true, "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}]
    }
  },
  "article": {
    "fetch_kind": "html",
    "content": [
      {"from": "css", "selector": "div.post_view div.post_content > article > div.post_article", "html": true},
      {"from": "css", "selector": "div.post_view div.post_content article", "html": true}
    ],
    "enrich": {
      "title": [{"from": "css", "selector": "div.post_title h3.post_subject > span:last-child", "text": true, "transform": [["collapse_ws"]]}],
      "author": [{"from": "attr", "selector": "div.post_info .nickname span[title]", "attr": "title", "transform": [["collapse_ws"]]}],
      "published_at": [{"from": "css", "selector": "div.post_author .view_count.date", "text": true, "transform": [["collapse_ws"], ["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}]
    }
  }
}''',
}


def _functional(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _IGNORE}


def _expected() -> dict[str, dict]:
    return {url: json.loads(text) for url, text in _GROUND_TRUTH.items()}


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject
    from engine.recognizers.clien import PATTERNS, _build

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    repro_ok, repro_detail = True, []
    for url, existing in _expected().items():
        built = _try(url)
        if built is None:
            repro_ok = False
            repro_detail.append(f"{url}: builder None")
            continue
        if _functional(built) != _functional(existing):
            repro_ok = False
            diffs = [k for k in set(_functional(built)) | set(_functional(existing))
                     if _functional(built).get(k) != _functional(existing).get(k)]
            repro_detail.append(f"{url}: diff keys {diffs}")
    cases.append(("roundtrip_reproduces_embedded_configs", repro_ok,
                  "4건 비교 · " + ("; ".join(repro_detail) or "all reproduced")))

    for url in _GROUND_TRUTH:
        cfg = recognize(url)
        board = json.loads(_GROUND_TRUTH[url])["board"]
        cases.append((f"recognize_{board}",
                      cfg is not None and cfg.get("_recognized_platform") == "clien" and cfg.get("_slug_board") == board,
                      f"platform={cfg and cfg.get('_recognized_platform')!r} slug={cfg and cfg.get('_slug_board')!r}"))
        cases.append((f"reject_none_{board}", recognize_reject(url) is None,
                      f"reject={recognize_reject(url)!r}"))

    cases.append(("www_and_apex_hosts",
                  recognize("https://clien.net/service/board/park") is not None
                  and recognize("https://www.clien.net/service/board/park") is not None,
                  "both clien.net and www.clien.net should match"))

    other_host = recognize("https://example.com/service/board/park")
    cases.append(("other_host_negative", other_host is None,
                  f"recognize→ {other_host and other_host.get('_recognized_platform')!r}"))

    same_host_neg = [
        "https://www.clien.net/service/board/cm_app",
        "https://www.clien.net/service/board/jirum",
        "https://www.clien.net/service/group/community",
        "https://www.clien.net/service/search?q=test",
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "clien"
        cases.append((f"same_host_neg[{u.split('clien.net')[1][:22]}]", not hit,
                      f"recognize→ {r and r.get('_recognized_platform')!r}"))

    return cases


def test_run() -> None:
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
