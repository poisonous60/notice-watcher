"""`engine.url_discovery.discover_board_candidates` — Firecrawl `/map` mock 테스트.

실제 API 호출 X (mock 사용). 비용 0, 네트워크 0.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import url_discovery


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """firecrawl_map_log.json 을 tmpdir 로 격리."""
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr(url_discovery, "_LOG_PATH", p)
    return p


class _FakeResp:
    def __init__(self, *, status_code=200, body=None, raise_json=False):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise json.JSONDecodeError("bad", "", 0)
        return self._body


class _FakeClient:
    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp
        self._raise = raise_exc
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def post(self, url, *, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self._raise is not None:
            raise self._raise
        return self._resp


def _patch_client(monkeypatch, client):
    def _factory(*args, **kwargs):
        return client
    monkeypatch.setattr(url_discovery.httpx, "Client", _factory)
    return client


def test_no_key_returns_empty(tmp_log):
    out = url_discovery.discover_board_candidates("https://x.example", "")
    assert out == []
    assert tmp_log.exists()
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "no_key"


def test_success_returns_unique_links(monkeypatch, tmp_log):
    resp = _FakeResp(body={"success": True, "links": [
        "https://x.example/board",
        "https://x.example/news",
        "https://x.example/board",  # duplicate
        "  ",
        123,  # non-string filtered
    ]})
    _patch_client(monkeypatch, _FakeClient(resp=resp))

    out = url_discovery.discover_board_candidates("https://x.example/", "key123")

    assert out == ["https://x.example/board", "https://x.example/news"]
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "ok"
    assert entry["count"] == 2
    assert entry["credit"] == 1


def test_http_error_returns_empty(monkeypatch, tmp_log):
    _patch_client(monkeypatch, _FakeClient(raise_exc=url_discovery.httpx.ConnectError("fail")))

    out = url_discovery.discover_board_candidates("https://x.example/", "key123")

    assert out == []
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "http_error"


def test_non_200_returns_empty(monkeypatch, tmp_log):
    resp = _FakeResp(status_code=429, body={})
    _patch_client(monkeypatch, _FakeClient(resp=resp))

    out = url_discovery.discover_board_candidates("https://x.example/", "key123")

    assert out == []
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "http_429"


def test_bad_json_returns_empty(monkeypatch, tmp_log):
    resp = _FakeResp(raise_json=True)
    _patch_client(monkeypatch, _FakeClient(resp=resp))

    out = url_discovery.discover_board_candidates("https://x.example/", "key123")

    assert out == []
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "bad_json"


def test_api_failure_returns_empty(monkeypatch, tmp_log):
    resp = _FakeResp(body={"success": False, "error": "rate limit"})
    _patch_client(monkeypatch, _FakeClient(resp=resp))

    out = url_discovery.discover_board_candidates("https://x.example/", "key123")

    assert out == []
    entry = json.loads(tmp_log.read_text(encoding="utf-8").strip())
    assert entry["status"] == "api_fail"


def test_request_body_shape(monkeypatch, tmp_log):
    client = _FakeClient(resp=_FakeResp(body={"success": True, "links": []}))
    _patch_client(monkeypatch, client)

    url_discovery.discover_board_candidates("https://x.example/", "mykey", limit=20)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://api.firecrawl.dev/v1/map"
    assert call["headers"]["Authorization"] == "Bearer mykey"
    assert call["json"] == {"url": "https://x.example/", "limit": 20, "includeSubdomains": False}


def test_log_disabled(monkeypatch, tmp_log):
    _patch_client(monkeypatch, _FakeClient(resp=_FakeResp(body={"success": True, "links": []})))

    url_discovery.discover_board_candidates("https://x.example/", "key", log=False)

    assert not tmp_log.exists()
