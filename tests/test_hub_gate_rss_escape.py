from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_register():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    rp = root / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_hub_gate_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(reg)
    return reg


def _hub_digest(feed_candidates: list[dict] | None = None) -> dict:
    return {
        "feed_candidates": feed_candidates or [],
        "list_candidates": {
            "html_repeating_patterns": [
                {
                    "href_pattern_guess": "https://www.wheresyoured.at/about",
                    "child_count": 12,
                },
                {
                    "href_pattern_guess": "https://www.wheresyoured.at/archive",
                    "child_count": 9,
                },
            ]
        },
    }


def test_heterogeneous_hub_skips_validated_rss_feed():
    reg = _load_register()
    digest = _hub_digest([
        {
            "url": "https://www.wheresyoured.at/feed",
            "validated": True,
            "item_count": 15,
            "root_tag": "rss",
        }
    ])

    assert reg._heterogeneous_hub_check(digest, "https://www.wheresyoured.at/") is None


def test_heterogeneous_hub_still_rejects_without_validated_rss_feed():
    reg = _load_register()
    digest = _hub_digest([
        {
            "url": "https://www.wheresyoured.at/feed",
            "validated": False,
            "item_count": 0,
            "root_tag": "html",
        }
    ])

    reason = reg._heterogeneous_hub_check(digest, "https://www.wheresyoured.at/")

    assert reason is not None
    assert "clean article cluster 0" in reason
