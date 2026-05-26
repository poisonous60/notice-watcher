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


# --- 2026-05-27 games-jp batch — announcement-tab escape ---

def _announce_tab_digest(
    *,
    patterns: list[dict],
    api_candidates: list[dict] | None = None,
    clicked_url: str | None = None,
    pagination_hints: list | None = None,
) -> dict:
    return {
        "feed_candidates": [],
        "list_candidates": {
            "html_repeating_patterns": patterns,
            "pagination_hints": pagination_hints or [],
        },
        "article_sample": {
            "api_candidates": api_candidates,
            "clicked_resolved_url": clicked_url,
        },
    }


def test_announcement_tab_escapes_via_article_api_identity():
    """granblue 류 — board path 가 /news/ 이고 reprobe article API 중 url_id_match=True 1+ 면 escape."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "https://granbluefantasy.jp/ja/news/", "child_count": 7},
        ],
        api_candidates=[
            {"url": "https://granbluefantasy.com/rcms-api/1/news/details/9704?cnt=1&_lang=ja",
             "url_id_match": True, "body_looks_html": True},
            {"url": "https://granbluefantasy.com/rcms-api/1/news-nav?_lang=ja",
             "url_id_match": False, "body_looks_html": True},
        ],
    )
    assert reg._heterogeneous_hub_check(digest, "https://granbluefantasy.jp/news/") is None


def test_announcement_tab_escapes_via_dense_cluster_under_board_path():
    """nexon 류 — cc>=20 cluster 가 board_path 아래로 가면 (placeholder 가 query 에 있어도) escape."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "/news/detail?id={n}-23a5e007", "child_count": 755,
             "sample_url": "https://www.nexon.co.jp/news/detail?id=20260521-23a5e007"},
            {"href_pattern_guess": "/ir/", "child_count": 8},
        ],
    )
    assert reg._heterogeneous_hub_check(digest, "https://www.nexon.co.jp/news/") is None


def test_announcement_tab_escapes_via_query_placeholder_recognition():
    """dense cluster 가 query placeholder 로 article shape 잡힌 경우 — escape 안 거치고도 통과 (article_cluster 인정)."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "/news/detail?id={n}", "child_count": 100,
             "sample_url": "https://x.example.com/news/detail?id=42"},
        ],
    )
    # API/click escape 미해당 — placeholder-in-query path 가 board_path 아래라 article_shape 로 잡혀 nav_max=0 → board.
    assert reg._heterogeneous_hub_check(digest, "https://x.example.com/news/") is None


def test_announcement_tab_escapes_via_clicked_article_url():
    """click resolved 가 진짜 article URL (depth>=2 + numeric/slug 마지막 segment) 이면 escape."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "/news/", "child_count": 6},
        ],
        clicked_url="https://example.com/news/12345/",
    )
    assert reg._heterogeneous_hub_check(digest, "https://example.com/news/") is None


def test_announcement_tab_still_rejects_when_no_board_signal():
    """announcement-tab 이라도 4 escape 신호 다 없으면 거부 유지 — false-accept 방지."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "/news/", "child_count": 5},
            {"href_pattern_guess": "/about/", "child_count": 8},
        ],
    )
    reason = reg._heterogeneous_hub_check(digest, "https://example.com/news/")
    assert reason is not None
    assert "clean article cluster 0" in reason


def test_root_url_not_affected_by_announce_tab_escapes():
    """root URL (`/`) 은 announcement-tab 아님 — 기존 거부 동작 유지."""
    reg = _load_register()
    digest = _announce_tab_digest(
        patterns=[
            {"href_pattern_guess": "/news/detail?id={n}", "child_count": 100,
             "sample_url": "https://example.com/news/detail?id=1"},
            {"href_pattern_guess": "/about/", "child_count": 12},
        ],
    )
    # board_path=/ — announce escape 안 들어감. cluster /news/detail 은 board_path 아래 검사도
    # board_path '/' 라 안 됨 → nav 로 처리. clean article cluster 0종.
    reason = reg._heterogeneous_hub_check(digest, "https://example.com/")
    assert reason is not None
