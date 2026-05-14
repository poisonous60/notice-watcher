"""probe.hydration.find_list_in_json — JSON blob 안 글 목록 배열 찾기."""
from __future__ import annotations


# 이 fixture 가 커버하는 @heuristic 함수들 (probe_smoke stage 5 coverage 검증용)
covers = ["find_list_in_json", "looks_like_row", "looks_rowish"]


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import find_list_in_json, _looks_like_row, _looks_rowish

    cases: list[tuple[str, bool, str]] = []

    # 1. typical — 원소 자체가 항목 (title+id)
    blob = {"data": {"items": [
        {"id": i, "title": f"t{i}", "createdAt": "2024-01-01"} for i in range(6)
    ]}}
    hits = find_list_in_json(blob, min_items=5)
    cases.append(("typical_items", len(hits) >= 1 and hits[0]["count"] == 6, f"got {len(hits)} hits"))
    if hits:
        cases.append(("typical_item_subpath_empty", hits[0]["item_subpath"] == "",
                      f"got {hits[0].get('item_subpath')!r}"))

    # 2. 엔벨로프 — feed:{title,id} 안에 들어있음
    blob = {"items": [
        {"feed": {"feedId": i, "title": f"t{i}"}, "user": {"name": "x"}} for i in range(6)
    ]}
    hits = find_list_in_json(blob, min_items=5)
    cases.append(("envelope_feed", len(hits) >= 1, f"got {len(hits)} hits"))
    if hits:
        cases.append(("envelope_item_subpath_feed", hits[0]["item_subpath"] == "feed",
                      f"got {hits[0].get('item_subpath')!r}"))

    # 3. 글-row 아님 — id 만 있고 title 없음 → 안 잡힘
    blob = {"items": [{"id": i} for i in range(10)]}
    hits = find_list_in_json(blob, min_items=5)
    cases.append(("no_title_no_match", len(hits) == 0, f"got {len(hits)} hits"))

    # 4. 너무 짧은 배열 — min_items 미달
    blob = {"items": [{"id": i, "title": f"t{i}"} for i in range(3)]}
    hits = find_list_in_json(blob, min_items=5)
    cases.append(("too_few_items", len(hits) == 0, f"got {len(hits)} hits"))

    # 5. _looks_like_row
    cases.append(("looks_like_row_item",
                  _looks_like_row({"id": 1, "title": "x"}) == "", ""))
    cases.append(("looks_like_row_envelope",
                  _looks_like_row({"feed": {"feedId": 1, "title": "x"}}) == "feed", ""))
    cases.append(("looks_like_row_no",
                  _looks_like_row({"foo": "bar"}) is None, ""))

    # 6. _looks_rowish (단순 isinstance + 키)
    cases.append(("looks_rowish_yes", _looks_rowish({"id": 1, "title": "x"}) is True, ""))
    cases.append(("looks_rowish_no_dict", _looks_rowish("xyz") is False, ""))
    cases.append(("looks_rowish_missing_id", _looks_rowish({"title": "x"}) is False, ""))

    return cases
