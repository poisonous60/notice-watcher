"""URL → slug, 출력 디렉토리 경로 헬퍼."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from ._heuristic import heuristic


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output" / "probe"
STATE_ROOT = PROJECT_ROOT / "output" / "state"


@heuristic
def url_to_slug(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path.strip('/')}"
    if parts.query:
        raw = f"{raw}_{parts.query}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return slug[:120] or "site"


def output_dir(slug: str) -> Path:
    d = OUTPUT_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file(slug: str) -> Path:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    return STATE_ROOT / f"{slug}.json"
