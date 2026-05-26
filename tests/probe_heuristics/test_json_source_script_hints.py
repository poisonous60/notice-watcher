"""HAR JSON candidates can point back to the JS source that constructs them."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory


covers = ["json_source_script_hints"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import traffic_api_candidates

    cases: list[tuple[str, bool, str]] = []
    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        data_file = tmp / "news.json"
        data_file.write_text(json.dumps([
            {"name": f"post {i}", "link_url": f"/news/{1000 + i}.html", "date": "2026/05/26"}
            for i in range(6)
        ]), encoding="utf-8")
        har = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://x.test/js/news.js", "headers": []},
                        "response": {
                            "status": 200,
                            "headers": [{"name": "Content-Type", "value": "application/javascript"}],
                            "content": {"mimeType": "application/javascript", "text": "url = '/cms-data/json/' + 'news_' + now_date + '.json';"},
                        },
                    },
                    {
                        "request": {"method": "GET", "url": "https://x.test/cms-data/json/news_202605.json", "headers": []},
                        "response": {
                            "status": 200,
                            "headers": [{"name": "Content-Type", "value": "application/json"}],
                            "content": {"mimeType": "application/json", "_file": data_file.name},
                        },
                        "_resourceType": "xhr",
                    },
                ]
            }
        }
        har_path = tmp / "traffic.har"
        har_path.write_text(json.dumps(har), encoding="utf-8")
        cands = traffic_api_candidates(har_path, page_url="https://x.test/news/")

    hints = cands[0].get("source_script_hints") if cands else []
    cases.append((
        "script_source_hint_attached",
        bool(hints) and hints[0]["script_url"] == "https://x.test/js/news.js" and "news_" in hints[0]["evidence"],
        f"cands={cands}",
    ))
    return cases
