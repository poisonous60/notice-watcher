"""probe._contract — validate_payload + OUTPUT_SCHEMA 메타 테스트.

핵심 6 케이스 (silent fail 차단 mechanism 보호):
1. happy validate — object + object_list 둘 다
2. 필수 키 누락 → ContractError
3. 모르는 키 + allow_extra=False → ContractError
4. payload_kind mismatch (dict 예상인데 list) → ContractError
5. 알 수 없는 파일명 → KeyError
6. OUTPUT_SCHEMA 6 종 완전성
"""
from __future__ import annotations


# stage 5 coverage 통과용 가상 식별자 — probe HEURISTICS 와 무관.
covers = ["contract_validate_payload"]


def run() -> list[tuple[str, bool, str]]:
    from probe._contract import (
        validate_payload, OUTPUT_SCHEMA, ContractError, get_contract,
    )

    cases: list[tuple[str, bool, str]] = []

    # 1. happy — object (list_candidates) + object_list (article_candidates 빈 list)
    happy_obj = {
        "first_article_url": "https://x.com/view/1",
        "html_repeating_patterns": [],
        "traffic_json_api_candidates": [],
        "hydration_list_candidates": [],
        "inline_js_data_candidates": [],
        "runtime_id_candidates": [],
    }
    try:
        validate_payload("list_candidates.json", happy_obj)
        validate_payload("article_candidates.json", [])
        validate_payload("article_click.json", {
            "requested_url": "https://x.com/news",
            "resolved_url": "https://x.com/news/1",
            "status": 200,
            "clicked_text": "News title",
            "clicked_href": "/news/1",
            "note": None,
            "consent_dismissed": 1,
        }, allow_extra=False)
        cases.append(("happy_object_and_object_list", True, ""))
    except ContractError as e:
        cases.append(("happy_object_and_object_list", False, f"unexpected raise: {e}"))

    # 2. 필수 키 누락 → ContractError
    try:
        validate_payload("list_candidates.json", {"first_article_url": None})
        cases.append(("missing_required_raises", False, "should have raised"))
    except ContractError as e:
        cases.append(("missing_required_raises", "missing required" in str(e), f"got {str(e)[:120]!r}"))

    # 3. allow_extra=False 일 때 모르는 키
    extra = dict(happy_obj)
    extra["NEW_UNKNOWN_KEY"] = 42
    try:
        validate_payload("list_candidates.json", extra, allow_extra=False)
        cases.append(("unknown_key_strict_raises", False, "should have raised"))
    except ContractError as e:
        cases.append(("unknown_key_strict_raises", "unknown" in str(e).lower(), f"got {str(e)[:120]!r}"))

    # 4. payload_kind mismatch — article_candidates 는 list 예상인데 dict 줌
    try:
        validate_payload("article_candidates.json", {"not": "a list"})
        cases.append(("payload_kind_mismatch_raises", False, "should have raised"))
    except ContractError as e:
        cases.append(("payload_kind_mismatch_raises",
                      "expected list" in str(e), f"got {str(e)[:120]!r}"))

    # 5. 알 수 없는 파일명 → KeyError
    try:
        get_contract("nonexistent.json")
        cases.append(("unknown_artifact_raises", False, "should have raised"))
    except KeyError:
        cases.append(("unknown_artifact_raises", True, ""))

    # 6. OUTPUT_SCHEMA 가 7 종 완전성 (산출물 종류 회귀 차단)
    expected = {
        "diagnosis.json", "list_candidates.json", "robots.json", "sitemap.json",
        "feed_candidates.json", "article_click.json", "article_candidates.json",
    }
    cases.append(("output_schema_completeness", set(OUTPUT_SCHEMA) == expected,
                  f"got {set(OUTPUT_SCHEMA)}"))

    return cases
