"""ConfigAdapter — 선언적 config 를 실행하는 범용 어댑터.

`BaseAdapter` 를 상속하므로 adapters/runner.py:collect_parallel 가 손으로 짠 어댑터와
동일하게 취급한다. strategy == "handwritten" 인 config 는 ConfigAdapter 가 아니라
adapters 패키지의 실제 클래스를 인스턴스화한다 → `make_adapter()` 사용.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .base_compat import BaseAdapter, NoticePost
from .config_schema import validate_config
from .strategies import get_strategy


# 엔진 공통 보수치(사이트별 Crawl-Delay 클램핑은 이번 스코프 밖 — config 가 더 *느린* 값을 주면 그걸 하한으로).
_DEFAULT_SLEEP_MIN = 3.0
_DEFAULT_SLEEP_MAX = 6.0


class ConfigAdapter(BaseAdapter):
    polite_sleep_min = _DEFAULT_SLEEP_MIN
    polite_sleep_max = _DEFAULT_SLEEP_MAX

    def __init__(self, config: dict, *, validate: bool = True):
        if validate:
            validate_config(config)
        if config.get("strategy") == "handwritten":
            raise ValueError("handwritten strategy 는 ConfigAdapter 가 아니라 make_adapter() 로 인스턴스화")
        self.cfg = config
        self.site = config["site"]
        self.board = str(config.get("board", "default"))
        self.host = self._derive_host(config) or self.site
        self._strategy = get_strategy(config["strategy"])

        ps = config.get("polite_sleep") or {}
        if "min" in ps:
            self.polite_sleep_min = max(_DEFAULT_SLEEP_MIN, float(ps["min"]))
        if "max" in ps:
            self.polite_sleep_max = max(_DEFAULT_SLEEP_MAX, float(ps["max"]), self.polite_sleep_min)
        if self.polite_sleep_max < self.polite_sleep_min:
            self.polite_sleep_max = self.polite_sleep_min

        # strategy 모듈이 쓰는 세션 핸들
        self._client = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    @staticmethod
    def _derive_host(config: dict) -> Optional[str]:
        lst = config.get("list") or {}
        tmpl = lst.get("url_template")
        if not tmpl:
            return None
        board = str(config.get("board", ""))
        try:
            rendered = tmpl.format_map(_MissingSafe(board=board, page=1, page_size=20))
        except Exception:
            rendered = tmpl
        netloc = urlsplit(rendered).netloc
        return netloc or None

    async def __aenter__(self) -> "ConfigAdapter":
        await self._strategy.open_session(self)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._strategy.close_session(self)

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        return await self._strategy.fetch_list(self, page=page, page_size=page_size)

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        return await self._strategy.fetch_article(self, post)


class _MissingSafe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def make_adapter(config: dict, *, validate: bool = True) -> BaseAdapter:
    """config → BaseAdapter 인스턴스. handwritten 이면 adapters 패키지의 실제 클래스."""
    if validate:
        validate_config(config)
    if config.get("strategy") == "handwritten":
        import adapters as _adapters_pkg

        name = config["adapter"]
        cls = getattr(_adapters_pkg, name, None)
        if cls is None:
            raise ValueError(f"handwritten adapter 클래스 없음: {name!r}")
        return cls(**(config.get("kwargs") or {}))
    return ConfigAdapter(config, validate=False)


def load_config(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def load_config_dir(directory: str | Path) -> list[tuple[str, dict]]:
    """디렉토리의 *.json config 들을 (slug, config) 리스트로. slug = 파일명(확장자 제외)."""
    d = Path(directory)
    out: list[tuple[str, dict]] = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        out.append((p.stem, load_config(p)))
    return out
