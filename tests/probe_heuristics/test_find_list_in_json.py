"""probe.hydration.find_list_in_json — JSON blob 안 글 목록 배열 찾기."""
from __future__ import annotations


# 이 fixture 가 커버하는 @heuristic 함수들 (probe_smoke stage 5 coverage 검증용)
covers = [
    "find_list_in_json", "looks_like_row", "looks_rowish",
    "is_identity_value", "has_row_identity", "has_title_key",
]


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import (
        find_list_in_json,
        _looks_like_row,
        _looks_rowish,
        _is_identity_value,
        _has_row_identity,
        _has_title_key,
    )

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

    # 7. _is_identity_value — value-shape guard
    cases.append(("identity_int_positive", _is_identity_value(155) is True, ""))
    cases.append(("identity_int_zero_ok", _is_identity_value(0) is True, "0 도 인정 (auto-inc 0)"))
    cases.append(("identity_bool_rejected", _is_identity_value(True) is False, "bool 거부"))
    cases.append(("identity_none_rejected", _is_identity_value(None) is False, ""))
    cases.append(("identity_empty_str_rejected", _is_identity_value("") is False, ""))
    cases.append(("identity_short_str_rejected", _is_identity_value("a") is False, "1자 미만"))
    cases.append(("identity_slug_ok", _is_identity_value("abc-123") is True, ""))
    cases.append(("identity_uuid_ok", _is_identity_value("a1b2c3d4-e5f6-7890") is True, ""))
    cases.append(("identity_dict_rejected", _is_identity_value({"x": 1}) is False, ""))
    cases.append(("identity_url_strict_rejects_slash", _is_identity_value("/news/1.html") is False,
                  "default(url_like=False) 는 slash 거부"))
    cases.append(("identity_url_like_accepts_slash",
                  _is_identity_value("/news/1.html", url_like=True) is True, ""))

    # 8. _has_row_identity — 새 *_id/*Id regex + URL key value-shape
    cases.append(("has_id_snake", _has_row_identity({"announce_id": 155}) is True, "umamusume"))
    cases.append(("has_id_camel", _has_row_identity({"iInfoId": 164243}) is True, "hoyoverse"))
    cases.append(("has_id_topics_id", _has_row_identity({"topics_id": 9704}) is True, "granblue"))
    cases.append(("has_id_url_key", _has_row_identity({"link_url": "/news/28000.html"}) is True, ""))
    cases.append(("has_id_clientId_with_empty", _has_row_identity({"clientId": ""}) is False, "value-shape 거부"))
    cases.append(("has_id_paid_rejected", _has_row_identity({"paid": True}) is False, "key/value 둘 다 거부"))
    cases.append(("has_id_grid_rejected", _has_row_identity({"grid": "x"}) is False, "key regex 미스"))
    cases.append(("has_id_id_token_rejected", _has_row_identity({"id_token": "abc"}) is False, "id_ prefix 거부"))

    # 9. _has_title_key — sTitle/articleTitle/post_subject
    cases.append(("title_fixed_title", _has_title_key({"title": "x"}) is True, ""))
    cases.append(("title_sTitle", _has_title_key({"sTitle": "x"}) is True, "hoyoverse Hungarian"))
    cases.append(("title_articleTitle", _has_title_key({"articleTitle": "x"}) is True, ""))
    cases.append(("title_post_subject", _has_title_key({"post_subject": "x"}) is True, ""))
    cases.append(("title_metadata_rejected", _has_title_key({"metadata": "x"}) is False, ""))
    cases.append(("title_hostname_rejected", _has_title_key({"hostname": "x"}) is False, ""))

    # 10. cross-site row detection (실세계 패턴 회귀)
    umamusume_like = {"information_list": [
        {"announce_id": i, "title": f"t{i}", "post_at": "2026-05-25"}
        for i in range(10)
    ]}
    hits_uma = find_list_in_json(umamusume_like, min_items=5)
    cases.append(("umamusume_like_detected", len(hits_uma) >= 1 and hits_uma[0]["count"] == 10,
                  f"got {len(hits_uma)} hits"))

    hoyoverse_like = {"data": {"list": [
        {"iInfoId": 164243 + i, "sTitle": f"t{i}", "sDate": "2026-05-25"}
        for i in range(7)
    ]}}
    hits_hoy = find_list_in_json(hoyoverse_like, min_items=5)
    cases.append(("hoyoverse_like_detected", len(hits_hoy) >= 1 and hits_hoy[0]["count"] == 7,
                  f"got {len(hits_hoy)} hits"))

    granblue_like = {"list": [
        {"topics_id": 9704 - i, "subject": f"t{i}", "inst_ymdhi": "2026-05-22T15:00:00",
         "post_time": "12:00:00", "slug": ""}
        for i in range(10)
    ]}
    hits_grb = find_list_in_json(granblue_like, min_items=5)
    cases.append(("granblue_like_detected", len(hits_grb) >= 1 and hits_grb[0]["count"] == 10,
                  f"got {len(hits_grb)} hits"))

    return cases
