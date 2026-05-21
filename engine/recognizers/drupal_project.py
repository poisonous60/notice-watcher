"""Drupal.org project releases -> release-history XML config."""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "host_drupal-org"

_RE = re.compile(r"//(?:www\.)?drupal\.org/project/([^/?#]+)/releases/?(?:[?#].*)?$", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    project = m.group(1)
    source_url = f"https://updates.drupal.org/release-history/{project}/current"
    return {
        "version": 1,
        "site": "drupal.org",
        "board": project,
        "strategy": "httpx_html",
        "_slug_board": "project",
        "_source_url": f"https://www.drupal.org/project/{project}/releases",
        "headers": {
            "User-Agent": UA,
            "Accept": "application/xml,text/xml,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": "https://www.drupal.org/",
        },
        "timeout": 20,
        "polite_sleep": {"min": 5, "max": 7},
        "list": {
            "url_template": source_url,
            "pagination": {"kind": "none"},
            "row_selector": "project > releases > release",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {"from": "css", "selector": "version", "text": True, "transform": [["strip"]]},
                ],
                "title": [
                    {"from": "css", "selector": "name", "text": True, "transform": [["collapse_ws"]]},
                ],
                "url": [
                    {"from": "css", "selector": "release_link", "text": True, "transform": [["strip"]]},
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "date",
                        "text": True,
                        "transform": [["strip"], ["unixtime_to_iso", "Z", "s"]],
                    },
                ],
                "summary": [
                    {
                        "from": "concat",
                        "parts": [
                            {"const": "Download: "},
                            {"from": "css", "selector": "download_link", "text": True, "transform": [["strip"]]},
                        ],
                    },
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [],
            "body_empty_acceptable": True,
        },
        "_note": (
            "Drupal.org project releases are protected by a Fastly client challenge on the HTML page. "
            "Use the official updates.drupal.org release-history XML endpoint instead."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
