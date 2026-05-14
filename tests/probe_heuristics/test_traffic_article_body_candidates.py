"""probe.extract.traffic_article_body_candidates — HAR → 단일 글 본문 JSON API 점수화."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _entry(*, url: str, body: object, content_type: str = "application/json",
           method: str = "GET", status: int = 200, request_body: str | None = None) -> dict:
    body_text = json.dumps(body) if not isinstance(body, str) else body
    return {
        "request": {"method": method, "url": url, "headers": [],
                    "postData": {"text": request_body} if request_body else {}},
        "response": {
            "status": status,
            "headers": [{"name": "Content-Type", "value": content_type}],
            "content": {"mimeType": content_type, "text": body_text},
        },
    }


def _write_har(entries: list[dict]) -> Path:
    har = {"log": {"entries": entries}}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".har", delete=False, encoding="utf-8")
    tmp.write(json.dumps(har))
    tmp.close()
    return Path(tmp.name)


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import traffic_article_body_candidates

    cases: list[tuple[str, bool, str]] = []

    # 1. typical — content 키 + HTML 본문 + url_id_match
    html_body = "<p>" + "글 본문 내용 " * 200 + "</p>"
    har_path = _write_har([
        _entry(url="https://api.example.com/article/12345",
               body={"data": {"content": html_body, "title": "t"}}),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/view/12345")
    cases.append(("typical_detected", len(out) >= 1, f"got {len(out)} candidates"))
    if out:
        c = out[0]
        cases.append(("body_field_path_to_content",
                      c["body_field_path"] == ["data", "content"], f"got {c['body_field_path']!r}"))
        cases.append(("body_looks_html", c["body_looks_html"] is True, f"got {c['body_looks_html']!r}"))
        cases.append(("url_id_match_true", c["url_id_match"] is True, f"got {c['url_id_match']!r}"))
    har_path.unlink(missing_ok=True)

    # 2. cross-site = 제외
    har_path = _write_har([
        _entry(url="https://other-domain.com/api/x",
               body={"content": "x" * 300}),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/view/1")
    cases.append(("cross_site_excluded", out == [], f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    # 3. Content-Type 이 JSON 아님 = 제외
    har_path = _write_har([
        _entry(url="https://api.example.com/article/12345",
               body=json.dumps({"content": "x" * 300}),
               content_type="text/html"),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/view/12345")
    cases.append(("non_json_ct_excluded", out == [], f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    # 4. 빈 본문 = 제외
    har_path = _write_har([
        _entry(url="https://api.example.com/x", body={}),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/")
    cases.append(("empty_body_excluded", out == [], f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    # 5. body_id_match — request body 안에 ID
    har_path = _write_har([
        _entry(url="https://api.example.com/get",
               body={"content": "x" * 300},
               method="POST",
               request_body=json.dumps({"articleId": 12345})),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/view/12345")
    if out:
        cases.append(("body_id_match_or_url_match",
                      out[0].get("url_id_match") or "12345" in (out[0].get("request_body_text") or ""),
                      f"got {out[0]!r}"))
    har_path.unlink(missing_ok=True)

    # 6. 정렬 — HTML > non-HTML
    har_path = _write_har([
        _entry(url="https://api.example.com/short",
               body={"summary": "a" * 250}),
        _entry(url="https://api.example.com/full",
               body={"content": "<p>" + "본문" * 300 + "</p>"}),
    ])
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/")
    if len(out) >= 2:
        cases.append(("html_higher_than_plain", out[0]["body_looks_html"] is True,
                      f"got top body_looks_html={out[0]['body_looks_html']}"))
    har_path.unlink(missing_ok=True)

    # 7. max_candidates 한도
    entries = [_entry(url=f"https://api.example.com/a{i}", body={"content": "x" * 300})
               for i in range(10)]
    har_path = _write_har(entries)
    out = traffic_article_body_candidates(har_path, article_url="https://example.com/",
                                          max_candidates=3)
    cases.append(("max_candidates_limited", len(out) <= 3, f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    # 8. 존재 안 하는 path
    out = traffic_article_body_candidates(Path("/nonexistent_xyz.har"))
    cases.append(("nonexistent_path", out == [], f"got {len(out)}"))

    # 9. 빈 HAR
    har_path = _write_har([])
    out = traffic_article_body_candidates(har_path)
    cases.append(("empty_har", out == [], f"got {len(out)}"))
    har_path.unlink(missing_ok=True)

    return cases
