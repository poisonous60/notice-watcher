"""Anthropic docs release notes overview -> handwritten adapter.

The page is a single static changelog document: each date is an ``h3`` and the
release-note rows are the following ``ul > li`` elements. A declarative config
cannot carry the preceding date into each list item, so this recognizer routes
the known release notes overview URL to a small handwritten parser.
"""
from __future__ import annotations

import re
from typing import Optional

# Keep the pre-existing fallback slug stable for this already-triaged URL:
# host_docs-anthropic-_en_<hash>. A more descriptive recognizer name would
# change the slug and require a slug-schema migration.
NAME = "host_docs-anthropic-"

_RE = re.compile(r"^https?://docs\.anthropic\.com/(?:docs/)?en/release-notes/overview/?(?:[?#].*)?$", re.I)
_URL = "https://docs.anthropic.com/en/release-notes/overview"
_BOARD = "en/release-notes/overview"
_SLUG_BOARD = "en"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return {
        "version": 1,
        "site": "docs.anthropic.com",
        "board": _BOARD,
        "strategy": "handwritten",
        "adapter": "AnthropicDocsReleaseNotesAdapter",
        "kwargs": {
            "board": _BOARD,
            "url": _URL,
            "timeout": 15,
        },
        "polite_sleep": {"min": 3, "max": 6},
        "_slug_board": _SLUG_BOARD,
        "_source_url": _URL,
        "_note": (
            "Anthropic docs release notes overview — h3 date headings followed by ul/li release-note rows. "
            "Handwritten parser carries each h3 date into subsequent li rows and hashes date+url+text for stable IDs."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
