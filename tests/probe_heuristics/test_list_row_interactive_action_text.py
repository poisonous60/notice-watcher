"""list_row_interactive_action_text 휴리스틱 fixture.

본문 없는 사이트 (게임 디렉토리 / 투표·설문 / 인터랙티브 SPA) 검출. KO/EN 액션 키워드 매칭.
"""
from __future__ import annotations

from probe.extract import list_row_interactive_action_text


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # 1) piku-like — 이상형월드컵 게임 카드. first_text 안 "시작하기" + "랭킹보기" + "이상형 월드컵" 매칭.
    piku_like = [{
        "selector": "div.row.equal > div.col-xs-6",
        "child_count": 10,
        "first_text": "박지훈 (1999) 안효섭 (1995) 한국 남자 배우 이상형 월드컵 당신의 취향은?? 시작하기 랭킹보기 공유 복사",
        "href_is_js": True,
        "sample_url": None,
    }]
    out = list_row_interactive_action_text(piku_like)
    cases.append((
        "piku_worldcup_detected",
        out is not None and out.get("is_interactive_action") is True and out.get("matched_row_count") == 1,
        f"out={out}",
    ))

    # 2) 정상 게시판 — 글 제목 list. 액션 키워드 없음 → None.
    normal_board = [{
        "selector": "table.list > tr.bb-row",
        "child_count": 20,
        "first_text": "공지: 4월 정기 점검 안내 / 2026-04-17 / 운영팀",
        "href_is_js": None,
        "sample_url": "https://example.com/notice/12345",
    }]
    out = list_row_interactive_action_text(normal_board)
    cases.append((
        "normal_board_no_match",
        out is None,
        f"out={out}",
    ))

    # 3) 카페 게시판 (한 row 에 "공유하기" 하나만 들어가도 키워드 1개 — 의미 신호 미달 → None).
    cafe_with_share_button = [{
        "selector": "div.list > div.post",
        "child_count": 15,
        "first_text": "오늘 처음 가입했어요 — 잘 부탁드립니다. 공유하기",
        "href_is_js": None,
        "sample_url": "https://cafe.example.com/post/567",
    }]
    out = list_row_interactive_action_text(cafe_with_share_button)
    cases.append((
        "single_keyword_no_match",
        out is None,
        f"out={out}",
    ))

    # 4) child_count < 5 인 row 는 skip (의미 있는 반복 X).
    small_count_with_keywords = [{
        "selector": "div",
        "child_count": 3,
        "first_text": "이상형 월드컵 시작하기 라운드 선택",
        "href_is_js": True,
        "sample_url": None,
    }]
    out = list_row_interactive_action_text(small_count_with_keywords)
    cases.append((
        "child_count_under_5_skipped",
        out is None,
        f"out={out}",
    ))

    # 5) EN 게임 사이트 — "Vote now" + "Round 1" 2개 매칭.
    en_voting_site = [{
        "selector": "div.poll-cards > div.card",
        "child_count": 8,
        "first_text": "Best K-Pop boy group 2026 Vote now Round 1 of 6 winner takes all",
        "href_is_js": True,
        "sample_url": None,
    }]
    out = list_row_interactive_action_text(en_voting_site)
    cases.append((
        "en_voting_site_detected",
        out is not None and out.get("is_interactive_action") is True
        and "Vote now" in out.get("matched_keyword_set", [])
        and "Round 1" in out.get("matched_keyword_set", []),
        f"out={out}",
    ))

    # 6) html_candidates 빈 리스트 → None (안전).
    cases.append((
        "empty_input_returns_none",
        list_row_interactive_action_text([]) is None,
        "empty list input",
    ))

    return cases
