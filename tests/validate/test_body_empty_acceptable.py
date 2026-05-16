"""`article.body_empty_acceptable` 플래그가 `generate.validate.validate_built_config` 의
article_body_len 체크를 hard=False 로 완화하는지 — fake adapter 로 검증.

본문이 본질적으로 없는 사이트 (검색결과 SERP / 인터랙티브 게임 디렉토리 / aggregator) opt-in 패턴.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from engine.base_compat import BaseAdapter, NoticePost
from generate.validate import validate_built_config


class _FakeAdapter(BaseAdapter):
    """fetch_list = 1건, fetch_article = 빈 본문 — validate 의 article_body_len 분기 자극."""

    def __init__(self, *, body_empty: bool = True, body_chars: int = 0):
        self.site = "fake.example.com"
        self.board = "x"
        self.host = self.site
        self._body_empty = body_empty
        self._body_chars = body_chars

    async def __aenter__(self):  # noqa: D401
        return self

    async def __aexit__(self, *exc):  # noqa: D401
        return None

    async def fetch_list(self, *, page: int = 1, page_size: int = 30):
        return [NoticePost(
            site=self.site, board=self.board,
            post_id="P1", title="T1", url="https://fake.example.com/p/P1",
        )]

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        content = "" if self._body_empty else ("x" * self._body_chars)
        return NoticePost(
            site=post.site, board=post.board, post_id=post.post_id,
            title=post.title, url=post.url, content_html=content,
        )


def _make_cfg(*, body_empty_acceptable: bool) -> dict:
    cfg: dict = {
        "version": 1,
        "site": "fake.example.com",
        "board": "x",
        "strategy": "handwritten",
        "adapter": "_FakeFlagAdapter",
        "kwargs": {},
        "list": {"url_template": "https://fake.example.com/list", "fields": {}},
        "article": {"url_template": "https://fake.example.com/p/{post_id}", "fetch_kind": "html"},
    }
    if body_empty_acceptable:
        cfg["article"]["body_empty_acceptable"] = True
    return cfg


def _run_validate(*, body_empty_acceptable: bool, body_chars: int) -> tuple[bool, list, list, str]:
    """validate 를 실행, (any_hard_fail, hard_failures, all_check_names, feedback) 반환."""
    cfg = _make_cfg(body_empty_acceptable=body_empty_acceptable)
    # make_adapter 우회 — 직접 fake adapter 의 logic 만 검증하는 게 목적.
    # validate_built_config 은 make_adapter(cfg) 부른 뒤 그 결과를 async with 함 →
    # cfg.strategy="handwritten" 으로 가짜 어댑터 클래스 끼우기 위해 adapters 패키지에 동적 추가.
    import adapters as _ad
    _ad._FakeFlagAdapter = lambda **kw: _FakeAdapter(  # type: ignore[attr-defined]
        body_empty=(body_chars == 0), body_chars=body_chars,
    )
    try:
        rep = asyncio.run(validate_built_config(cfg, fetch_articles=1))
    finally:
        try:
            delattr(_ad, "_FakeFlagAdapter")
        except AttributeError:
            pass
    hard = rep.hard_failures()
    names = [c.name for c in rep.checks]
    return (bool(hard), hard, names, rep.feedback_text())


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # 1) body_empty_acceptable=true + body 0자 → article_body_len 통과 (hard fail 없어야)
    has_hard, hard, names, fb = _run_validate(body_empty_acceptable=True, body_chars=0)
    cases.append((
        "flag_true_body_empty_no_hard_fail",
        not has_hard,
        f"hard_failures={[(c.name, c.detail) for c in hard]} names={names}",
    ))

    # 2) body_empty_acceptable=true + body 50자(<100) → 여전히 hard fail 없어야
    has_hard, hard, _names, _fb = _run_validate(body_empty_acceptable=True, body_chars=50)
    cases.append((
        "flag_true_body_short_no_hard_fail",
        not has_hard,
        f"hard_failures={[(c.name, c.detail) for c in hard]}",
    ))

    # 3) flag 없음 + body 0자 → article_body_len 가 hard fail 이어야 (기존 동작 유지)
    has_hard, hard, _names, _fb = _run_validate(body_empty_acceptable=False, body_chars=0)
    article_body_hard = any(c.name == "article_body_len" and c.hard and not c.ok for c in hard)
    cases.append((
        "flag_off_body_empty_hard_fail_kept",
        article_body_hard,
        f"hard_failures={[(c.name, c.detail) for c in hard]}",
    ))

    # 4) flag 없음 + body 200자 → 모두 pass (기존 정상 동작)
    has_hard, hard, _names, _fb = _run_validate(body_empty_acceptable=False, body_chars=200)
    cases.append((
        "flag_off_body_ok_pass",
        not has_hard,
        f"hard_failures={[(c.name, c.detail) for c in hard]}",
    ))

    # 5) schema 가 flag 받아들이는지
    from engine.config_schema import validate_config
    try:
        validate_config(_make_cfg(body_empty_acceptable=True))
        schema_ok = True
        msg = "validate_config OK"
    except Exception as e:
        schema_ok = False
        msg = f"{type(e).__name__}: {e}"
    cases.append(("schema_accepts_flag", schema_ok, msg))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}  ({msg})")
        if not ok:
            fail += 1
    raise SystemExit(0 if fail == 0 else 1)
