"""URL → slug, 출력 디렉토리 경로 헬퍼.

slug 생성 본체는 `engine.slug.url_to_slug` — 여기선 그것을 `@heuristic` 로 wrap 해 re-export 만 한다.
probe 의 휴리스틱 추적 (`scripts/probe_smoke.py` stage 5) 이 `@heuristic` 데코레이터를 보고 mtime 회귀를
잡으므로 wrapper 가 필요.
"""
from __future__ import annotations

from pathlib import Path

from engine.slug import url_to_slug as _engine_url_to_slug

from ._heuristic import heuristic


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output" / "probe"
STATE_ROOT = PROJECT_ROOT / "output" / "state"


@heuristic
def url_to_slug(url: str) -> str:
    """`<platform>_<board-id>_<hash>` 형식 (≤100자). 정의·세부는 `engine.slug.url_to_slug`."""
    return _engine_url_to_slug(url)


def output_dir(slug: str) -> Path:
    d = OUTPUT_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file(slug: str) -> Path:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    return STATE_ROOT / f"{slug}.json"
