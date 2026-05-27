"""probe.extract._cross_host_list_api_allowed — cross-host sister-brand API escape (FP guard).

2026-05-27 박힘: granblue (.jp page → .com rcms-api) 류 brand-host 분리 패턴.
광고/트래커 cross-host (googleads / facebook / analytics) 는 _AD_TRACKER_RE 가 위에서 차단 —
여기 도달했더라도 brand match + strong row semantic 미충족이면 거부.
"""
from __future__ import annotations


covers = ["cross_host_list_api_allowed"]


def _hit(sample_first: dict) -> dict:
    """find_list_in_json hit 흉내 (sample_first 만 채움)."""
    return {"count": 10, "path": "", "item_subpath": "", "sample_keys": list(sample_first.keys()),
            "sample_first": sample_first}


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _cross_host_list_api_allowed

    cases: list[tuple[str, bool, str]] = []

    # 1. granblue 류 — 자매 brand (.jp ↔ .com), strong row semantic (title+id+date)
    hits = [_hit({"topics_id": 9704, "subject": "x", "inst_ymdhi": "2026-05-22T15:00:00", "post_time": "12:00:00"})]
    ok = _cross_host_list_api_allowed(
        "https://granbluefantasy.com/rcms-api/1/news?cnt=10",
        "https://granbluefantasy.jp/news/",
        hits,
    )
    cases.append(("granblue_brand_match_strong_semantic", ok is True, ""))

    # 2. brand match 안 됨 — page=granblue, api=akamai (CDN)
    hits = [_hit({"topics_id": 9704, "subject": "x", "inst_ymdhi": "..."})]
    ok = _cross_host_list_api_allowed(
        "https://prd-info-umamusume.akamaized.net/data.json",
        "https://granbluefantasy.jp/news/",
        hits,
    )
    cases.append(("brand_mismatch_rejected", ok is False, "akamai != granblue"))

    # 3. brand match OK 지만 row semantic 약함 (date 없음)
    hits = [_hit({"clientId": "abc", "title": "x"})]  # url/date 없음
    ok = _cross_host_list_api_allowed(
        "https://granbluefantasy.com/api/clients",
        "https://granbluefantasy.jp/news/",
        hits,
    )
    cases.append(("weak_semantic_rejected", ok is False, "url/date 없으면 reject"))

    # 4. row semantic OK 지만 brand 너무 짧음 (5자 미만 회피)
    hits = [_hit({"topics_id": 1, "title": "x", "createdAt": "..."})]
    ok = _cross_host_list_api_allowed(
        "https://abc.com/api/news",
        "https://xyz.jp/news/",
        hits,
    )
    cases.append(("short_brand_rejected", ok is False, "'abc'/'xyz' < 6자"))

    # 5. 빈 list_hits
    ok = _cross_host_list_api_allowed(
        "https://granbluefantasy.com/rcms-api/1/news",
        "https://granbluefantasy.jp/news/",
        [],
    )
    cases.append(("empty_hits_rejected", ok is False, ""))

    # 6. hoyoverse 류 — sTitle + iInfoId + sDate (camel/snake/Hungarian)
    hits = [_hit({"iInfoId": 164243, "sTitle": "x", "sDate": "2026-05-25"})]
    # 다른 brand 도 같은 사이트 (hoyoverse.com vs hoyoverse.com — registrable 같으면 _same_site
    # 가 위에서 잡아 cross-host 도달 안 함. 여기는 brand match 가 같은 registrable 다른 subdomain
    # 같이 fail 한 경우 가정.)
    ok = _cross_host_list_api_allowed(
        "https://sg-public-api-static.someprovider.com/getContentList",  # 다른 brand
        "https://www.hoyoverse.com/news/",
        hits,
    )
    cases.append(("hoyoverse_brand_mismatch_provider", ok is False, ""))

    # 7. facebook notification cross-host (negative — brand mismatch)
    hits = [_hit({"notificationId": "abc123", "title": "x", "createdAt": "..."})]
    ok = _cross_host_list_api_allowed(
        "https://graph.facebook.com/v18.0/me/notifications",
        "https://granbluefantasy.jp/news/",
        hits,
    )
    cases.append(("facebook_brand_mismatch", ok is False, ""))

    return cases
