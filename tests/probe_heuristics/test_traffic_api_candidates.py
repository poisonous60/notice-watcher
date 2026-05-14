"""probe.extract.traffic_api_candidates — HAR → 글 목록 JSON API 점수화."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _har_entry(*, url: str, method: str = "GET", status: int = 200,
               resource_type: str = "xhr", body: object = None,
               content_type: str = "application/json") -> dict:
    """HAR entry 한 건 합성."""
    body_text = json.dumps(body) if body is not None else "{}"
    return {
        "_resourceType": resource_type,
        "request": {"method": method, "url": url, "headers": [], "postData": {"text": None}},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": content_type}],
            "content": {"mimeType": content_type, "text": body_text},
        },
    }


def _write_har(entries: list[dict]) -> Path:
    """엔트리 리스트 → 임시 .har 파일 경로."""
    har = {"log": {"entries": entries}}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False, encoding="utf-8")
    tmp.write(json.dumps(har))
    tmp.close()
    return Path(tmp.name)


def _list_body(n: int = 10) -> dict:
    """{title, id, createdAt} 항목 n 개 = find_list_in_json 매칭."""
    return {"items": [{"id": i, "title": f"t{i}", "createdAt": "2024-01-01"} for i in range(n)]}


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import traffic_api_candidates

    cases: list[tuple[str, bool, str]] = []

    # 1. typical — 같은 사이트 + xhr + feed 경로 + 200 + GET + 항목 10건 = 고득점
    har_path = _write_har([
        _har_entry(url="https://api.example.com/feed?page=1", body=_list_body(10)),
    ])
    out = traffic_api_candidates(har_path, page_url="https://example.com/board")
    cases.append(("typical_detected", len(out) >= 1, f"got {len(out)} candidates"))
    if out:
        cases.append(("typical_relevance_positive", out[0]["relevance_score"] > 0,
                      f"got score={out[0].get('relevance_score')}"))
        cases.append(("typical_has_list_hits", len(out[0].get("list_hits", [])) >= 1, ""))
    har_path.unlink(missing_ok=True)

    # 2. 광고 트래커 도메인 = 제외
    har_path = _write_har([
        _har_entry(url="https://googletagmanager.com/gtag/config?id=GA-X", body=_list_body(10)),
        _har_entry(url="https://doubleclick.net/pixel?event=view", body=_list_body(10)),
    ])
    out = traffic_api_candidates(har_path, page_url="https://example.com/board")
    cases.append(("ad_tracker_excluded", out == [], f"got {len(out)} candidates"))
    har_path.unlink(missing_ok=True)

    # 3. 다른 호스트(third-party) = 제외 (page_url 있을 때)
    har_path = _write_har([
        _har_entry(url="https://other-site.com/api/feed", body=_list_body(10)),
    ])
    out = traffic_api_candidates(har_path, page_url="https://example.com/board")
    cases.append(("cross_site_excluded", out == [],
                  f"got {len(out)} candidates (cross-site should be filtered)"))
    har_path.unlink(missing_ok=True)

    # 4. 항목 5개 미만 = find_list_in_json 매칭 X
    har_path = _write_har([
        _har_entry(url="https://api.example.com/x?q=1", body=_list_body(3)),
    ])
    out = traffic_api_candidates(har_path, page_url="https://example.com/")
    cases.append(("too_few_items", out == [], f"got {len(out)} candidates"))
    har_path.unlink(missing_ok=True)

    # 5. URL 경로 키워드(feed/board/list/notice) 점수 차이
    har_feed = _write_har([
        _har_entry(url="https://api.example.com/feed?p=1", body=_list_body(10)),
    ])
    har_misc = _write_har([
        _har_entry(url="https://api.example.com/data?p=1", body=_list_body(10)),
    ])
    out_feed = traffic_api_candidates(har_feed, page_url="https://example.com/")
    out_misc = traffic_api_candidates(har_misc, page_url="https://example.com/")
    cases.append(("list_path_keyword_higher_score",
                  out_feed[0]["relevance_score"] > out_misc[0]["relevance_score"],
                  f"feed={out_feed[0]['relevance_score']}, misc={out_misc[0]['relevance_score']}"))
    har_feed.unlink(missing_ok=True)
    har_misc.unlink(missing_ok=True)

    # 6. 정렬 — 점수 순 내림차순
    har_path = _write_har([
        _har_entry(url="https://api.example.com/data", body=_list_body(10)),       # 낮음
        _har_entry(url="https://api.example.com/feed?limit=20", body=_list_body(20)),  # 높음
    ])
    out = traffic_api_candidates(har_path, page_url="https://example.com/")
    cases.append(("sorted_desc",
                  len(out) >= 2 and out[0]["relevance_score"] >= out[1]["relevance_score"],
                  f"got scores={[c['relevance_score'] for c in out]}"))
    har_path.unlink(missing_ok=True)

    # 7. status 4xx 페널티 (200 +2 / 4xx -3, 5점 차이)
    har_ok = _write_har([_har_entry(url="https://api.example.com/feed", status=200,
                                    body=_list_body(10))])
    har_404 = _write_har([_har_entry(url="https://api.example.com/feed", status=404,
                                     body=_list_body(10))])
    out_ok = traffic_api_candidates(har_ok, page_url="https://example.com/")
    out_404 = traffic_api_candidates(har_404, page_url="https://example.com/")
    cases.append(("status_4xx_penalty",
                  out_ok[0]["relevance_score"] - out_404[0]["relevance_score"] == 5,
                  f"ok={out_ok[0]['relevance_score']}, 404={out_404[0]['relevance_score']}"))
    har_ok.unlink(missing_ok=True)
    har_404.unlink(missing_ok=True)

    # 8. document resourceType 페널티
    har_path = _write_har([
        _har_entry(url="https://api.example.com/feed", resource_type="document",
                   body=_list_body(10)),
    ])
    out_doc = traffic_api_candidates(har_path, page_url="https://example.com/")
    har_path.unlink(missing_ok=True)
    har_path = _write_har([
        _har_entry(url="https://api.example.com/feed", resource_type="xhr",
                   body=_list_body(10)),
    ])
    out_xhr = traffic_api_candidates(har_path, page_url="https://example.com/")
    har_path.unlink(missing_ok=True)
    cases.append(("xhr_higher_than_document",
                  out_xhr[0]["relevance_score"] > out_doc[0]["relevance_score"],
                  f"xhr={out_xhr[0]['relevance_score']}, doc={out_doc[0]['relevance_score']}"))

    # 9. 빈 HAR
    har_path = _write_har([])
    out = traffic_api_candidates(har_path, page_url="https://example.com/")
    cases.append(("empty_har", out == [], f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    # 10. 존재 안 하는 path
    out = traffic_api_candidates(Path("/nonexistent_har_path_xyz.har"))
    cases.append(("nonexistent_path", out == [], f"got {len(out)}"))

    return cases
