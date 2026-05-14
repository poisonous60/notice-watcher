"""probe.extract._registrable + _same_site — multi-TLD aware 도메인 비교."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _registrable, _same_site

    cases: list[tuple[str, bool, str]] = []

    # _registrable
    cases.append(("regist_simple_com", _registrable("a.b.example.com") == "example.com",
                  f"got {_registrable('a.b.example.com')!r}"))
    cases.append(("regist_co_kr", _registrable("sub.example.co.kr") == "example.co.kr",
                  f"got {_registrable('sub.example.co.kr')!r}"))
    cases.append(("regist_co_jp", _registrable("a.b.example.co.jp") == "example.co.jp",
                  f"got {_registrable('a.b.example.co.jp')!r}"))
    cases.append(("regist_naked_2label", _registrable("example.com") == "example.com",
                  f"got {_registrable('example.com')!r}"))
    cases.append(("regist_single_label", _registrable("localhost") == "localhost",
                  f"got {_registrable('localhost')!r}"))
    cases.append(("regist_empty", _registrable("") == "", f"got {_registrable('')!r}"))
    cases.append(("regist_uppercase_normalized", _registrable("FOO.example.COM") == "example.com",
                  f"got {_registrable('FOO.example.COM')!r}"))

    # _same_site
    cases.append(("same_two_subdomains_com",
                  _same_site("https://a.example.com/x", "https://b.example.com/y") is True, ""))
    cases.append(("same_two_subdomains_co_kr",
                  _same_site("https://m.daum.net/x", "https://www.daum.net/y") is True, ""))
    cases.append(("same_naver_game",
                  _same_site("https://game.naver.com/x", "https://comm-api.game.naver.com/y") is True,
                  ""))
    cases.append(("diff_sites",
                  _same_site("https://example.com/x", "https://other.com/y") is False, ""))
    cases.append(("diff_co_kr_vs_com",
                  _same_site("https://example.co.kr/x", "https://example.com/y") is False, ""))
    cases.append(("empty_host",
                  _same_site("/relative/path", "https://x.com/") is False, ""))

    return cases
