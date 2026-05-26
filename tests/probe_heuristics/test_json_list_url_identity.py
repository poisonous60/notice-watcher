"""JSON list rows may identify posts by URL rather than an explicit id."""
from __future__ import annotations


covers = ["json_list_url_identity"]


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import find_list_in_json

    monthly_news = [
        {
            "date": "2026/05/26",
            "thumbnail_path": f"/cms-data/uploads/{i}.jpg",
            "text_content": "body",
            "link_url": f"/news/{28000 + i}.html",
            "name": f"news {i}",
            "movie_icon": "false",
        }
        for i in range(8)
    ]

    wrapped = [{"feed": {"title": f"post {i}", "url": f"/p/{i}"}} for i in range(6)]

    cases: list[tuple[str, bool, str]] = []
    hits = find_list_in_json(monthly_news, min_items=5)
    cases.append((
        "top_level_url_identity_list_detected",
        bool(hits) and hits[0]["path"] == "" and hits[0]["item_subpath"] == "",
        f"hits={hits}",
    ))

    nested_hits = find_list_in_json({"items": wrapped}, min_items=5)
    cases.append((
        "nested_url_identity_list_detected",
        bool(nested_hits) and nested_hits[0]["path"] == "items" and nested_hits[0]["item_subpath"] == "feed",
        f"hits={nested_hits}",
    ))
    return cases
