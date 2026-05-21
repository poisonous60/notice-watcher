"""IACR conference sites -> httpx_html important dates feed.

IACR conference microsites share the same static Bootstrap layout for the
current-year landing page. The useful watch surface is the "Important dates"
card: each ``div.customCardRow.row`` has a date heading and one event text.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "iacr_conf"

_CONF_HOSTS = (
    "crypto",
    "eurocrypt",
    "asiacrypt",
    "tcc",
    "pkc",
    "fse",
    "ches",
    "rwc",
)

_RE = re.compile(
    r"^https?://(" + "|".join(_CONF_HOSTS) + r")\.iacr\.org/(\d{4})/?(?:[?#].*)?$",
    re.I,
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    conf = m.group(1).lower()
    year = m.group(2)
    host = f"{conf}.iacr.org"
    list_url = f"https://{host}/{year}/"
    return {
        "version": 1,
        "site": host,
        "board": year,
        "strategy": "httpx_html",
        "_slug_board": year,
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": list_url,
        },
        "timeout": 15,
        "polite_sleep": {"min": 3, "max": 6},
        "list": {
            "url_template": list_url,
            "row_selector": "article.customCard > div.customCardRow.row",
            "fields": {
                "post_id": [
                    {
                        "from": "css",
                        "selector": "h6.dateTitle",
                        "text": True,
                        "transform": [
                            ["collapse_ws"],
                            ["replace", ",", ""],
                            ["replace", " ", "-"],
                        ],
                    }
                ],
                "title": [
                    {
                        "from": "concat",
                        "parts": [
                            {
                                "from": "css",
                                "selector": "h6.dateTitle",
                                "text": True,
                                "transform": [["collapse_ws"]],
                            },
                            {"const": " - "},
                            {
                                "from": "css",
                                "selector": "p",
                                "text": True,
                                "transform": [["collapse_ws"]],
                            },
                        ],
                    }
                ],
                "url": [
                    {
                        "from": "template",
                        "value": f"{list_url}#{{post_id}}",
                    }
                ],
                "summary": [
                    {
                        "from": "css",
                        "selector": "p",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {
                    "from": "css",
                    "selector": "article.customCard",
                    "html": True,
                }
            ],
            "body_empty_acceptable": True,
        },
        "_source_url": list_url,
        "_note": (
            f"IACR {conf.upper()} {year} conference landing page — known-platform "
            "recognizer for the shared Important dates card "
            "(article.customCard > div.customCardRow.row). post_id is the normalized "
            "date label; item URL points to the landing page fragment."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
