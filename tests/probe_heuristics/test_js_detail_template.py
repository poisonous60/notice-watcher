"""Inline javascript detail URL template extraction."""
from __future__ import annotations


covers = ["extract_js_detail_template"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import extract_js_detail_template

    cases: list[tuple[str, bool, str]] = []

    html = """
    <html><head><script>
    function goView(seq) {
      location.href = '/kbiz/notice/view.do?seq=' + seq + '&menuCd=MENU01';
    }
    function ignored(x) { location.href = '/x?x=' + x; }
    </script></head><body>
      <ul>
        <li><a href="javascript:goView('12345')">첫 글</a></li>
        <li><a onclick="goView(12346); return false;">둘째 글</a></li>
      </ul>
    </body></html>
    """
    hits = extract_js_detail_template(html, base_url="https://www.kbiz.or.kr/list.do?menuCd=MENU01")
    cases.append(("goView_template",
                  hits and hits[0].get("function") == "goView"
                  and hits[0].get("detail_url_template") == "https://www.kbiz.or.kr/kbiz/notice/view.do?seq={post_id}&menuCd=MENU01",
                  f"got {hits!r}"))
    cases.append(("sample_id",
                  hits and hits[0].get("sample_id") == "12345",
                  f"got {hits!r}"))

    no_hits = extract_js_detail_template('<a href="/view.do?no=1">글</a>', base_url="https://x.test/list.do")
    cases.append(("plain_href_no_hit", no_hits == [], f"got {no_hits!r}"))
    return cases

