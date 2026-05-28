import asyncio
from types import SimpleNamespace

from engine.strategies import httpx_json


def test_httpx_json_list_values_accepts_dict_rows(monkeypatch):
    async def fake_get_json(adapter, url):
        return {
            "results": {
                "1": {"pk": 116, "title": "Pinned", "published_at": "2026-04-04T18:34:17+00:00"},
                "2": {"pk": 202, "title": "Latest", "published_at": "2026-05-26T13:41:48+00:00"},
            }
        }

    monkeypatch.setattr(httpx_json, "_get_json", fake_get_json)
    adapter = SimpleNamespace(
        site="example.com",
        board="news",
        cfg={
            "site": "example.com",
            "board": "news",
            "strategy": "httpx_json",
            "list": {
                "url_template": "https://example.com/api/news",
                "list_path": ["results"],
                "list_values": True,
                "fields": {
                    "post_id": [{"from": "json", "path": ["pk"], "transform": [["to_str"]]}],
                    "title": [{"from": "json", "path": ["title"]}],
                    "published_at": [{"from": "json", "path": ["published_at"]}],
                    "url": [{"from": "template", "value": "https://example.com/news/{post_id}"}],
                },
            },
        },
    )

    posts = asyncio.run(httpx_json.fetch_list(adapter, page=1, page_size=10))

    assert [p.post_id for p in posts] == ["116", "202"]
    assert [p.title for p in posts] == ["Pinned", "Latest"]
