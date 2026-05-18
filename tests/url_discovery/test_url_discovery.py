"""`engine.url_discovery.discover_board_candidates` — robots/sitemap/crawl mock 테스트.

실제 네트워크 호출 X. httpx.Client transport 를 MockTransport 로 갈아끼움.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import pytest

from engine import url_discovery


# ---- helpers --------------------------------------------------------------- #

def _make_client_factory(monkeypatch, route_map: dict):
    """{method+url: (status, content, headers)} dict 받아서 httpx.Client 를 MockTransport 로 패치.

    method 미스 = 404. URL 매칭 = 정확 (query/fragment 포함).
    """
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method.upper()} {str(request.url)}"
        if key not in route_map:
            return httpx.Response(404)
        spec = route_map[key]
        if len(spec) == 2:
            status, content = spec
            headers = {}
        else:
            status, content, headers = spec
        if isinstance(content, str):
            return httpx.Response(status, text=content, headers=headers)
        return httpx.Response(status, content=content, headers=headers)

    transport = httpx.MockTransport(handler)

    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(url_discovery.httpx, "Client", patched_client)


def _sitemap_urlset(*locs):
    items = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</urlset>"
    )


def _sitemap_index(*sm_urls):
    items = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sm_urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</sitemapindex>"
    )


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr(url_discovery, "_LOG_PATH", p)
    return p


# ---- tests ----------------------------------------------------------------- #

def test_bad_url_returns_empty(tmp_log):
    out = url_discovery.discover_board_candidates("not-a-url")
    assert out == []
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "bad_url"


def test_robots_sitemap_then_urlset(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "User-agent: *\nSitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset(
                "https://x.example/board",
                "https://x.example/news",
                "https://x.example/board",  # duplicate — dedup
            )),
        "GET https://x.example/": (200, "<html></html>"),
    })

    out = url_discovery.discover_board_candidates("https://x.example/")

    assert "https://x.example/board" in out
    assert "https://x.example/news" in out
    assert len([u for u in out if u == "https://x.example/board"]) == 1  # dedup
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "ok"


def test_no_robots_default_sitemap(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt": (404, ""),
        "HEAD https://x.example/sitemap.xml": (200, ""),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset("https://x.example/p1", "https://x.example/p2")),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/p1" in out
    assert "https://x.example/p2" in out


def test_sitemap_index_recursion(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap_index.xml\n"),
        "GET https://x.example/sitemap_index.xml":
            (200, _sitemap_index("https://x.example/sm1.xml", "https://x.example/sm2.xml")),
        "GET https://x.example/sm1.xml":
            (200, _sitemap_urlset("https://x.example/a", "https://x.example/b")),
        "GET https://x.example/sm2.xml":
            (200, _sitemap_urlset("https://x.example/c")),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert set(["https://x.example/a", "https://x.example/b", "https://x.example/c"]).issubset(set(out))


def test_sitemap_gzip(monkeypatch, tmp_log):
    raw = _sitemap_urlset("https://x.example/gz1", "https://x.example/gz2").encode()
    gz = gzip.compress(raw)
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml.gz\n"),
        "GET https://x.example/sitemap.xml.gz": (200, gz),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/gz1" in out
    assert "https://x.example/gz2" in out


def test_page_anchor_crawl(monkeypatch, tmp_log):
    html = """<html><body>
        <a href="/notice">notice</a>
        <a href="/about">about</a>
        <a href="https://x.example/news?p=1">news</a>
        <a href="https://other.example/x">other host</a>
        <a href="javascript:void(0)">js</a>
        <a href="mailto:a@b">mail</a>
        <a href="#frag">fragment</a>
    </body></html>"""
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt": (404, ""),
        "HEAD https://x.example/sitemap.xml": (404, ""),
        "HEAD https://x.example/sitemap_index.xml": (404, ""),
        "HEAD https://x.example/sitemap.xml.gz": (404, ""),
        "GET https://x.example/": (200, html),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/notice" in out
    assert "https://x.example/about" in out
    assert "https://x.example/news?p=1" in out
    # 외부 host 제외
    assert all("other.example" not in u for u in out)
    # 무시 스킴/프래그먼트 제외
    assert all(not u.startswith("javascript:") for u in out)


def test_combined_sources_dedup(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset("https://x.example/notice")),
        "GET https://x.example/":
            (200, '<html><body><a href="/notice">x</a><a href="/board">y</a></body></html>'),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert out.count("https://x.example/notice") == 1
    assert "https://x.example/board" in out


def test_normalize_drops_fragment_keeps_query(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt": (404, ""),
        "HEAD https://x.example/sitemap.xml": (404, ""),
        "HEAD https://x.example/sitemap_index.xml": (404, ""),
        "HEAD https://x.example/sitemap.xml.gz": (404, ""),
        "GET https://x.example/":
            (200, '<html><body><a href="/view?id=1#section">v</a></body></html>'),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/view?id=1" in out


def test_all_sources_fail_returns_empty(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt": (500, ""),
        "HEAD https://x.example/sitemap.xml": (404, ""),
        "HEAD https://x.example/sitemap_index.xml": (404, ""),
        "HEAD https://x.example/sitemap.xml.gz": (404, ""),
        "GET https://x.example/": (404, ""),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert out == []


def test_malformed_sitemap_xml_ignored(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml": (200, "<not valid xml"),
        "GET https://x.example/":
            (200, '<html><body><a href="/p">p</a></body></html>'),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    # sitemap 망가졌어도 page crawl 건짐
    assert "https://x.example/p" in out


def test_host_strict_filter(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset(
                "https://x.example/ok",
                "https://other.example/no",  # 다른 host
                "https://sub.x.example/no",  # 다른 host (subdomain 도 strict)
            )),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert out == ["https://x.example/ok"]


# ---- codex 리뷰 반영 추가 테스트 ---------------------------------------- #

def _sitemap_urlset_no_ns(*locs):
    """namespace 없는 sitemap (실제 웹에 종종 보임)."""
    items = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset>{items}</urlset>'


def _sitemap_index_no_ns(*sm_urls):
    items = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sm_urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex>{items}</sitemapindex>'


def test_namespace_less_urlset(monkeypatch, tmp_log):
    """codex MAJOR 1 — namespace 누락 sitemap 도 parse 가능해야."""
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset_no_ns("https://x.example/n1", "https://x.example/n2")),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/n1" in out
    assert "https://x.example/n2" in out


def test_namespace_less_sitemapindex(monkeypatch, tmp_log):
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/idx.xml\n"),
        "GET https://x.example/idx.xml":
            (200, _sitemap_index_no_ns("https://x.example/sm.xml")),
        "GET https://x.example/sm.xml":
            (200, _sitemap_urlset_no_ns("https://x.example/idx-child")),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/idx-child" in out


def test_head_fallback_to_range_get(monkeypatch, tmp_log):
    """codex MINOR — HEAD 거부 (405) 시 Range GET 폴백."""
    seen_methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/sitemap.xml":
            if request.method == "HEAD":
                return httpx.Response(405)
            if request.method == "GET":
                # Range GET 200 — HEAD 폴백 후 _head_exists 가 True 로 보고 sitemap 진짜 GET
                return httpx.Response(200, content=_sitemap_urlset(
                    "https://x.example/from-range").encode())
            return httpx.Response(404)
        if path == "/":
            return httpx.Response(200, text="<html></html>")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(url_discovery.httpx, "Client",
                        lambda *a, **k: real_client(*a, transport=transport, **k))

    out = url_discovery.discover_board_candidates("https://x.example/")
    assert "https://x.example/from-range" in out
    # HEAD 시도 후 Range GET (Range 헤더) 시도 흔적
    assert any(m.startswith("HEAD") for m in seen_methods)


def test_board_like_priority_within_cap(monkeypatch, tmp_log):
    """codex MAJOR 3 — cap 자를 때 board-like URL 우선."""
    monkeypatch.setattr(url_discovery, "_MAX_TOTAL", 3)
    # 5 candidate 중 3 만 살아남아야. board-like 가 살아야.
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml\n"),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap_urlset(
                "https://x.example/about",         # score: 1 (depth)
                "https://x.example/team",          # score: 1
                "https://x.example/contact",       # score: 1
                "https://x.example/board",         # score: 3+1 = 4 ← 살아야
                "https://x.example/notice/list",   # score: 3+1 = 4 ← 살아야
            )),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    assert len(out) == 3
    assert "https://x.example/board" in out
    assert "https://x.example/notice/list" in out


def test_canonical_redirect_host_allowed(monkeypatch, tmp_log):
    """codex MAJOR 2 — x.example → www.x.example redirect 후 final host 의 URL 도 허용."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        host = request.url.host
        # x.example 의 어떤 요청도 www.x.example 로 redirect
        if host == "x.example":
            return httpx.Response(
                301,
                headers={"Location": f"https://www.x.example{path}"},
            )
        if host == "www.x.example":
            if path == "/robots.txt":
                return httpx.Response(200, text="Sitemap: https://www.x.example/sitemap.xml\n")
            if path == "/sitemap.xml":
                return httpx.Response(200, text=_sitemap_urlset(
                    "https://www.x.example/notice"))
            if path == "/":
                return httpx.Response(200, text='<html><body><a href="/board">b</a></body></html>')
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(url_discovery.httpx, "Client",
                        lambda *a, **k: real_client(*a, transport=transport, **k))

    out = url_discovery.discover_board_candidates("https://x.example/")
    # redirect 후 www.x.example 가 final host — sitemap/anchor 결과 (다른 host 처럼 보이지만) 살아야
    assert "https://www.x.example/notice" in out
    assert "https://www.x.example/board" in out


def test_log_rotation(monkeypatch, tmp_log):
    """codex MINOR — log line 누적 시 rotation."""
    monkeypatch.setattr(url_discovery, "_MAX_LOG_LINES", 10)
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt": (404, ""),
        "HEAD https://x.example/sitemap.xml": (404, ""),
        "HEAD https://x.example/sitemap_index.xml": (404, ""),
        "HEAD https://x.example/sitemap.xml.gz": (404, ""),
        "GET https://x.example/": (200, "<html></html>"),
    })
    # 15 호출 → rotation 후 5 lines 만 남아야 (MAX/2)
    for _ in range(15):
        url_discovery.discover_board_candidates("https://x.example/")
    lines = tmp_log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) <= 10


def test_gzip_bomb_capped(monkeypatch, tmp_log):
    """codex MAJOR 4 — gzip decompress 결과가 cap 넘으면 reject."""
    monkeypatch.setattr(url_discovery, "_MAX_RESPONSE_BYTES", 1024)
    # 작은 gzip 인데 압축률 좋아 plain 이 1KB 넘는 케이스
    big_text = "<urlset>" + "<url><loc>https://x.example/" + "a" * 10 + "</loc></url>" * 200 + "</urlset>"
    gz = gzip.compress(big_text.encode())
    _make_client_factory(monkeypatch, {
        "GET https://x.example/robots.txt":
            (200, "Sitemap: https://x.example/sitemap.xml.gz\n"),
        "GET https://x.example/sitemap.xml.gz": (200, gz),
        "GET https://x.example/": (200, "<html></html>"),
    })
    out = url_discovery.discover_board_candidates("https://x.example/")
    # cap 넘으면 ValueError → 빈 list (또는 page crawl 만)
    # page crawl 도 빈 HTML 이라 0건 — 모두 0건
    assert out == []
