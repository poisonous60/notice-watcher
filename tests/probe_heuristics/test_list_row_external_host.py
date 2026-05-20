"""probe.extract.list_row_external_host — list row sample_url host 가 base host 와 다른 비율 신호.

검색결과/aggregator (Google Scholar, 뉴스 모음 등) 검출용. external_ratio≥0.8 이면 article body
통합 추출 불가 — config 작성 시 article 섹션 생략 또는 skip_status:[200] 박을 신호.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import list_row_external_host

    cases: list[tuple[str, bool, str]] = []

    # 1. 모든 row 가 외부 도메인 (Google Scholar 같은 검색결과)
    cands = [
        {"selector": "div.r", "child_count": 10, "sample_url": "https://files.eric.ed.gov/pdf/1.pdf",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "div.r", "child_count": 10, "sample_url": "https://api.taylorfrancis.com/x.pdf",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://scholar.google.com/scholar?q=x")
    cases.append(("all_external",
                  out is not None and out["external_count"] == 2 and out["external_ratio"] == 1.0
                  and out["base_host"] == "scholar.google.com" and len(out["sample_external_urls"]) == 2,
                  f"got {out!r}"))

    # 2. 모든 row 가 same host
    cands = [
        {"selector": "li.post", "child_count": 20, "sample_url": "https://board.example.com/view/123",
         "href_common_prefix": "/view/", "href_is_js": None},
        {"selector": "li.post", "child_count": 20, "sample_url": "https://board.example.com/view/124",
         "href_common_prefix": "/view/", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://board.example.com/list")
    cases.append(("all_same_host",
                  out is not None and out["external_count"] == 0 and out["external_ratio"] == 0.0,
                  f"got {out!r}"))

    # 3. child_count < 5 후보는 제외
    cands = [
        {"selector": "tr.tiny", "child_count": 3, "sample_url": "https://external.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://example.com/board")
    cases.append(("small_pattern_skipped", out is None, f"got {out!r}"))

    # 4. href_is_js 후보 제외
    cands = [
        {"selector": "li", "child_count": 10, "sample_url": "https://external.com/x",
         "href_common_prefix": "javascript:", "href_is_js": True},
    ]
    out = list_row_external_host(cands, base_url="https://example.com/board")
    cases.append(("js_href_skipped", out is None, f"got {out!r}"))

    # 5. same-host 인데 query-only sibling (pagination) — 제외돼야 함
    cands = [
        {"selector": "a.page", "child_count": 9, "sample_url": "https://scholar.google.com/scholar?start=10&q=x",
         "href_common_prefix": "/scholar?start=", "href_is_js": None},
        {"selector": "div.r", "child_count": 10, "sample_url": "https://files.eric.ed.gov/pdf/1.pdf",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://scholar.google.com/scholar?q=x")
    cases.append(("pagination_excluded",
                  out is not None and out["total_count"] == 1 and out["external_ratio"] == 1.0,
                  f"got {out!r}"))

    # 6. http(s) 아닌 sample_url — 제외
    cands = [
        {"selector": "li", "child_count": 10, "sample_url": "mailto:x@y.com",
         "href_common_prefix": "mailto:", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://example.com/board")
    cases.append(("non_http_skipped", out is None, f"got {out!r}"))

    # 7. base_url 없음 → None
    out = list_row_external_host(
        [{"selector": "li", "child_count": 10, "sample_url": "https://x.com/a",
          "href_common_prefix": "https://", "href_is_js": None}],
        base_url="",
    )
    cases.append(("empty_base_url_none", out is None, f"got {out!r}"))

    # 8. 혼합 (5건 중 4건 external = 0.8)
    cands = [
        {"selector": "li.r", "child_count": 10, "sample_url": "https://ext1.com/a",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://ext2.com/b",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://ext3.com/c",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://ext4.com/d",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://example.com/view/1",
         "href_common_prefix": "/view/", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://example.com/board")
    cases.append(("mixed_4_of_5",
                  out is not None and out["external_count"] == 4 and out["total_count"] == 5
                  and out["external_ratio"] == 0.8,
                  f"got {out!r}"))

    # 9. multi_host_hub: 3+ unique external hosts + ratio≥0.95 → True (tistory root 류).
    cands = [
        {"selector": "li.r", "child_count": 10, "sample_url": "https://a.tistory.com/post/1",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://b.tistory.com/post/2",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://policy.daum.net/policy/info",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://www.tistory.com/")
    cases.append(("multi_host_hub_tistory_positive",
                  out is not None and out["multi_host_hub"] is True
                  and len(out["unique_external_hosts"]) == 3
                  and out["external_ratio"] == 1.0,
                  f"got {out!r}"))

    # 10. multi_host_hub: 단일 external host (single sponsor) → False — poly-pizza FP 가드.
    cands = [
        {"selector": "li", "child_count": 10,
         "sample_url": "https://wawasensei.dev/courses/react?utm=PolyPizza",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://poly.pizza/")
    cases.append(("multi_host_hub_poly_pizza_negative",
                  out is not None and out["multi_host_hub"] is False
                  and len(out["unique_external_hosts"]) == 1
                  and out["external_ratio"] == 1.0,
                  f"got {out!r}"))

    # 11. multi_host_hub: 2 unique hosts → False (임계 3 미달).
    cands = [
        {"selector": "li", "child_count": 10, "sample_url": "https://a.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li", "child_count": 10, "sample_url": "https://b.com/y",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://hub.example.com/")
    cases.append(("multi_host_hub_two_hosts_below_threshold",
                  out is not None and out["multi_host_hub"] is False
                  and len(out["unique_external_hosts"]) == 2,
                  f"got {out!r}"))

    # 12. multi_host_hub: 3 unique hosts but ratio 0.6 — base path 가 깊어서 internal 행이 같은 호스트 카운트됨.
    cands = [
        {"selector": "li.r", "child_count": 10, "sample_url": "https://a.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://b.com/y",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://c.com/z",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://hub.example.com/post/1",
         "href_common_prefix": "/post/", "href_is_js": None},
        {"selector": "li.r", "child_count": 10, "sample_url": "https://hub.example.com/post/2",
         "href_common_prefix": "/post/", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://hub.example.com/list")
    cases.append(("multi_host_hub_ratio_below_threshold",
                  out is not None and out["multi_host_hub"] is False
                  and out["external_ratio"] == 0.6,
                  f"got {out!r}"))

    # 13. multi_host_hub: sibling subdomain only — False (2026-05-20 fix).
    # m.dcinside.com ↔ gall.dcinside.com/game.dcinside.com/www.dcinside.com 인프라 분리.
    cands = [
        {"selector": "li", "child_count": 10, "sample_url": "https://gall.dcinside.com/board/view/?id=maple&no=1",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li", "child_count": 10, "sample_url": "https://game.dcinside.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li", "child_count": 10, "sample_url": "https://www.dcinside.com/y",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://m.dcinside.com/board/maple")
    cases.append(("multi_host_hub_sibling_subdomain_negative",
                  out is not None and out["multi_host_hub"] is False
                  and len(out["unique_external_hosts"]) == 3
                  and out.get("base_registered_domain") == "dcinside.com",
                  f"got {out!r}"))

    # 14. multi_host_hub: 1 sibling + 2 다른 etld+1 → True (sibling 있어도 *다른* etld+1 섞이면 hub).
    cands = [
        {"selector": "li", "child_count": 10, "sample_url": "https://other.dcinside.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li", "child_count": 10, "sample_url": "https://example.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
        {"selector": "li", "child_count": 10, "sample_url": "https://other.com/x",
         "href_common_prefix": "https://", "href_is_js": None},
    ]
    out = list_row_external_host(cands, base_url="https://m.dcinside.com/")
    cases.append(("multi_host_hub_mixed_etld_positive",
                  out is not None and out["multi_host_hub"] is True
                  and len(out["unique_external_hosts"]) == 3,
                  f"got {out!r}"))

    return cases
