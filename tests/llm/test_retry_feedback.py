from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate.generator import _enrich_retry_feedback  # noqa: E402


class _Report:
    def __init__(self, text: str) -> None:
        self._text = text

    def feedback_text(self) -> str:
        return self._text


def test_infra_failure_does_not_tell_agent_to_change_selector_direction():
    feedback = _enrich_retry_feedback(
        _Report(
            "실행 중 에러: 실행 실패: Error: Page.goto: net::ERR_NAME_NOT_RESOLVED "
            "at https://www.gamecity.ne.jp/news/"
        ),
        {
            "strategy": "playwright_html",
            "list": {"row_selector": "#ajax_news > a.news-news-list__item.undefined"},
            "article": {},
        },
        {
            "list_candidates": {
                "traffic_json_api_candidates": [{"url": "https://example.com/api"}],
                "inline_js_data_candidates": [{"kind": "json_island"}],
            },
            "feed_candidates": [{"url": "https://example.com/feed.xml"}],
        },
        [
            {
                "n": 1,
                "strategy": "playwright_html",
                "rows": "#ajax_news > a.news-news-list__item.undefined",
                "fails": ["fetch_list"],
                "fails_detail": ["Page.goto: net::ERR_NAME_NOT_RESOLVED"],
            },
            {
                "n": 2,
                "strategy": "playwright_html",
                "rows": "#ajax_news > a.news-news-list__item.undefined",
                "fails": ["fetch_list"],
                "fails_detail": ["Temporary failure in name resolution"],
            },
        ],
    )

    assert "selector/strategy 가 틀렸다는 증거가 아니" in feedback
    assert "**방향 자체**" not in feedback
    assert "strategy 자체 또는 selector root 를 바꿔라" not in feedback
    assert "strategy 자체를 바꿔라" not in feedback
    assert "같은 방향 X" not in feedback
    assert "방향 전환 근거 아님" in feedback
    assert "probe 가 지지한 strategy/selector 를 유지" in feedback
