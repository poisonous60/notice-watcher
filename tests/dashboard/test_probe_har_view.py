"""Dashboard Probe HAR view-model regression tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard import har_view  # noqa: E402


def _entry(url: str, content_type: str, body: str, *, resource_type: str = "xhr") -> dict:
    return {
        "_resourceType": resource_type,
        "request": {"method": "GET", "url": url, "headers": []},
        "response": {
            "status": 200,
            "headers": [{"name": "content-type", "value": content_type}],
            "content": {"mimeType": content_type, "text": body},
        },
    }


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="probe_har_view_test_") as td:
        root = Path(td)
        slug = "host_example-com_news_1234abcd"
        out = root / slug
        out.mkdir()
        (out / "diagnosis.json").write_text(
            json.dumps({"url": "https://example.com/news/", "verdict": "headless 필요"}),
            encoding="utf-8",
        )
        (out / "list_candidates.json").write_text(
            json.dumps({
                "first_article_url": "https://example.com/news/10001",
                "html_repeating_patterns": [{"sample_url": "https://example.com/news/10001"}],
                "future_har_summary_signal": {"source": "traffic.har", "count": 1},
            }),
            encoding="utf-8",
        )
        list_body = {
            "items": [
                {
                    "id": 10000 + i,
                    "title": f"Post {i}",
                    "url": f"https://example.com/news/{10000 + i}",
                    "createdAt": "2026-05-27T00:00:00Z",
                }
                for i in range(6)
            ]
        }
        article_body = {"post": {"body": "<p>" + ("본문 " * 80) + "</p>"}}
        har = {
            "log": {
                "entries": [
                    _entry("https://example.com/api/news?page=2", "application/json", json.dumps(list_body)),
                    _entry("https://example.com/api/news/10001", "application/json", json.dumps(article_body)),
                    _entry("https://example.com/feed.xml", "application/rss+xml", "<rss><channel/></rss>"),
                ]
            }
        }
        (out / "traffic.har").write_text(json.dumps(har), encoding="utf-8")
        no_har = root / "host_nohar-example_news_abcdef12"
        no_har.mkdir()
        (no_har / "diagnosis.json").write_text(
            json.dumps({"url": "https://nohar.example/news/", "verdict": "정적 HTTP로 충분"}),
            encoding="utf-8",
        )

        rows = har_view.list_probe_runs(probe_root=root)
        search_rows = har_view.list_probe_runs(probe_root=root, q="nohar")
        detail = har_view.build_har_detail(slug, "traffic.har", probe_root=root)
        sections = {s["key"]: s for s in (detail or {}).get("sections", [])}
        artifact_rows = {
            row["key"]
            for section in (detail or {}).get("artifact_sections", [])
            if section["source"] == "list_candidates.json"
            for row in section["rows"]
        }

        cases.append(("lists_probe_run_with_har", any(r["slug"] == slug and r["has_har"] for r in rows), str(rows)))
        cases.append(("search_finds_probe_run_without_har",
                      len(search_rows) == 1 and search_rows[0]["har_count"] == 0, str(search_rows)))
        cases.append(("summary_counts_entries", detail and detail["summary"]["entry_count"] == 3, str(detail)))
        cases.append(("shows_json_api_candidate",
                      bool(sections["traffic_json_api_candidates"]["items"]), str(sections.get("traffic_json_api_candidates"))))
        cases.append(("shows_article_body_candidate",
                      bool(sections["traffic_article_body_candidates"]["items"]), str(sections.get("traffic_article_body_candidates"))))
        cases.append(("shows_rss_candidate",
                      bool(sections["rss_feed_urls"]["items"]), str(sections.get("rss_feed_urls"))))
        cases.append(("shows_har_pagination_hint",
                      bool(sections["pagination_hints"]["items"]), str(sections.get("pagination_hints"))))
        cases.append(("shows_future_summary_key_without_template_change",
                      "future_har_summary_signal" in artifact_rows, str(artifact_rows)))

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {'' if ok else d[:300]}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
