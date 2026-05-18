"""`probe.discover.fetch_sitemaps` — robots.txt 의 Sitemap: 라인 + 표준 경로 폴백 +
재귀 sitemapindex + gzip + namespace 유무 + board-like 점수 정렬 + byte cap 검증.

실제 네트워크 X — httpx.MockTransport 로 격리. tmpdir 에 sitemap.json 산출.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import pytest

from probe import discover


# ---- helpers --------------------------------------------------------------- #

def _make_transport(route_map: dict, fallback=lambda req: httpx.Response(404)):
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method.upper()} {str(request.url)}"
        spec = route_map.get(key)
        if spec is None:
            return fallback(request)
        if len(spec) == 2:
            status, content = spec
            headers = {}
        else:
            status, content, headers = spec
        if isinstance(content, str):
            return httpx.Response(status, text=content, headers=headers)
        return httpx.Response(status, content=content, headers=headers)
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, transport: httpx.MockTransport):
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)
    monkeypatch.setattr(discover.httpx, "Client", factory)


def _sitemap(*locs, ns: bool = True):
    items = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    if ns:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{items}</urlset>")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset>{items}</urlset>'


def _sitemap_index(*sm_urls, ns: bool = True):
    items = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sm_urls)
    if ns:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{items}</sitemapindex>")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex>{items}</sitemapindex>'


# ---- tests ----------------------------------------------------------------- #

def test_bad_url_returns_empty(tmp_path):
    info = discover.fetch_sitemaps(page_url="not-a-url",
                                    robots_sitemaps=[], out_dir=tmp_path)
    assert info["candidates"] == []
    assert info["error"]
    # sitemap.json 작성
    assert (tmp_path / "sitemap.json").exists()


def test_robots_sitemap_seed_then_urlset(monkeypatch, tmp_path):
    transport = _make_transport({
        "GET https://x.example/sitemap.xml":
            (200, _sitemap("https://x.example/board", "https://x.example/about")),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert "https://x.example/board" in urls
    assert "https://x.example/about" in urls
    # board > about (board-like score)
    assert urls.index("https://x.example/board") < urls.index("https://x.example/about")


def test_no_robots_default_sitemap_fallback(monkeypatch, tmp_path):
    transport = _make_transport({
        "HEAD https://x.example/sitemap.xml": (200, ""),
        "GET https://x.example/sitemap.xml":
            (200, _sitemap("https://x.example/notice", "https://x.example/p1")),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=[],  # robots 의 Sitemap 없음
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert "https://x.example/notice" in urls
    assert "https://x.example/p1" in urls


def test_sitemap_index_recursive(monkeypatch, tmp_path):
    transport = _make_transport({
        "GET https://x.example/idx.xml":
            (200, _sitemap_index("https://x.example/sm1.xml", "https://x.example/sm2.xml")),
        "GET https://x.example/sm1.xml":
            (200, _sitemap("https://x.example/a", "https://x.example/b")),
        "GET https://x.example/sm2.xml":
            (200, _sitemap("https://x.example/c")),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/idx.xml"],
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert set(["https://x.example/a", "https://x.example/b", "https://x.example/c"]).issubset(set(urls))


def test_gzip_sitemap(monkeypatch, tmp_path):
    raw = _sitemap("https://x.example/gz1").encode()
    gz = gzip.compress(raw)
    transport = _make_transport({
        "GET https://x.example/sitemap.xml.gz": (200, gz),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml.gz"],
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert "https://x.example/gz1" in urls


def test_namespace_less_urlset(monkeypatch, tmp_path):
    """ns 누락 sitemap 도 parse 가능."""
    transport = _make_transport({
        "GET https://x.example/sitemap.xml":
            (200, _sitemap("https://x.example/p1", ns=False)),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert "https://x.example/p1" in urls


def test_host_filter_strict(monkeypatch, tmp_path):
    transport = _make_transport({
        "GET https://x.example/sitemap.xml":
            (200, _sitemap(
                "https://x.example/ok",
                "https://other.example/no",
                "https://sub.x.example/no",  # subdomain 도 reject
            )),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    urls = [c["url"] for c in info["candidates"]]
    assert urls == ["https://x.example/ok"]


def test_board_like_priority_sorts(monkeypatch, tmp_path):
    transport = _make_transport({
        "GET https://x.example/sitemap.xml":
            (200, _sitemap(
                "https://x.example/about",        # depth 1 만
                "https://x.example/notice/list",  # notice keyword + depth
                "https://x.example/board",        # board keyword + depth
                "https://x.example/view?id=1",    # id query
            )),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    scores = {c["url"]: c["score"] for c in info["candidates"]}
    # board-like > about
    assert scores["https://x.example/notice/list"] > scores["https://x.example/about"]
    assert scores["https://x.example/board"] > scores["https://x.example/about"]
    # candidates 가 score 내림차순
    urls_ordered = [c["url"] for c in info["candidates"]]
    assert urls_ordered.index("https://x.example/about") == len(urls_ordered) - 1


def test_malformed_xml_ignored(monkeypatch, tmp_path):
    transport = _make_transport({
        "GET https://x.example/sitemap.xml": (200, "<not valid xml"),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    assert info["candidates"] == []
    # 에러 카운트 증가
    assert info["stats"]["errors"] >= 1


def test_all_fail_returns_empty(monkeypatch, tmp_path):
    transport = _make_transport({
        "HEAD https://x.example/sitemap.xml": (404, ""),
        "HEAD https://x.example/sitemap_index.xml": (404, ""),
        "HEAD https://x.example/sitemap.xml.gz": (404, ""),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=[],
        out_dir=tmp_path,
    )
    assert info["candidates"] == []
    assert info["error"] is None  # fail-soft (전체 실패는 아니라 0건)


def test_gzip_bomb_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(discover, "_MAX_SITEMAP_BYTES", 1024)
    big = "<urlset>" + "<url><loc>https://x.example/" + "a" * 10 + "</loc></url>" * 500 + "</urlset>"
    gz = gzip.compress(big.encode())
    transport = _make_transport({
        "GET https://x.example/sitemap.xml.gz": (200, gz),
    })
    _patch_client(monkeypatch, transport)

    info = discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml.gz"],
        out_dir=tmp_path,
    )
    # decompress cap 도달 → 그 sitemap 만 errors, 후보 0건
    assert info["candidates"] == []


def test_read_robots_extracts_sitemap_lines(monkeypatch, tmp_path):
    """probe/discover.read_robots 가 Sitemap: 라인 sitemaps 필드에 박는지."""
    transport = _make_transport({
        "GET https://x.example/robots.txt":
            (200, "User-agent: *\nDisallow: /admin\n"
                  "Sitemap: https://x.example/sitemap.xml\n"
                  "Sitemap: https://x.example/sitemap_blog.xml\n"),
    })
    _patch_client(monkeypatch, transport)

    info = discover.read_robots(page_url="https://x.example/", out_dir=tmp_path)
    assert info["sitemaps"] == [
        "https://x.example/sitemap.xml",
        "https://x.example/sitemap_blog.xml",
    ]
    # disallow + crawl_delay 영향 X
    assert info["disallow"] == ["/admin"]


def test_sitemap_json_payload_contract(monkeypatch, tmp_path):
    """sitemap.json 이 contract validate 통과 (모든 필수 키 존재)."""
    transport = _make_transport({
        "GET https://x.example/sitemap.xml":
            (200, _sitemap("https://x.example/notice")),
    })
    _patch_client(monkeypatch, transport)

    discover.fetch_sitemaps(
        page_url="https://x.example/",
        robots_sitemaps=["https://x.example/sitemap.xml"],
        out_dir=tmp_path,
    )
    p = tmp_path / "sitemap.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    # 필수 필드
    for k in ("page_url", "sitemap_urls_tried", "candidates", "stats"):
        assert k in data
    # candidates item 필수 필드
    if data["candidates"]:
        item = data["candidates"][0]
        assert "url" in item and "score" in item
