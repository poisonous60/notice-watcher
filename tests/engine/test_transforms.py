from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.transforms import apply_chain


def test_date_only_to_iso_accepts_slash_dates():
    assert apply_chain("2018/12/02", [["date_only_to_iso", "+00:00"]]) == "2018-12-02T00:00:00+00:00"
