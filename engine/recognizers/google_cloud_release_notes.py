"""Google Cloud release notes -> official Atom feed adapter."""
from __future__ import annotations

import re
from typing import Optional

NAME = "host_cloud-google-co"

_RE = re.compile(r"^https?://(?:docs\.)?cloud\.google\.com/release-notes/?(?:[?#].*)?$", re.I)
_URL = "https://cloud.google.com/release-notes"
_FEED_URL = "https://cloud.google.com/feeds/gcp-release-notes.xml"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return {
        "version": 1,
        "site": "cloud.google.com",
        "board": "release-notes",
        "strategy": "handwritten",
        "adapter": "GoogleCloudReleaseNotesAdapter",
        "kwargs": {
            "board": "release-notes",
            "feed_url": _FEED_URL,
            "timeout": 15.0,
        },
        "polite_sleep": {"min": 3, "max": 6},
        "_slug_board": "release-notes",
        "_source_url": _URL,
        "_note": (
            "Google Cloud release notes — official Atom feed. "
            "The HTML page is large and probe can timeout; the feed is the documented subscription channel. "
            "Adapter splits each date entry into product/kind release-note posts with stable hashes."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
