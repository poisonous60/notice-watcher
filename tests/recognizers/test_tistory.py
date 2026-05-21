"""engine.recognizers.tistory — Tistory subdomain → TistoryRssAdapter config.

URL 폼 다양함 (개별 글 entry-slug/숫자, 카테고리, 태그, 루트) — 모두 같은 host 기준 config 로 묶임.
`www.tistory.com/` (multi-blog hub) 은 article_page_reject 가 먼저 잡기에 여기선 None 이어야 함.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.tistory import _build, PATTERNS

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        if m is None:
            return None
        return _build(m, url)

    cases: list[tuple[str, bool, str]] = []

    # 1) 개별 글 entry-slug URL — 사용자가 실제로 줄 폼 (leedakyeong FAILED 케이스)
    cfg = _try("https://leedakyeong.tistory.com/entry/Python-pandas-tutorial-drop-duplicates-in-pandas")
    ok = (cfg is not None and cfg.get("adapter") == "TistoryRssAdapter"
          and cfg.get("kwargs", {}).get("host") == "leedakyeong.tistory.com"
          and cfg.get("_slug_board") == "leedakyeong")
    cases.append(("entry_slug_url", ok, f"got {cfg and cfg.get('kwargs')!r}"))

    # 2) 개별 글 숫자 URL (kevin0960 류)
    cfg = _try("https://kevin0960.tistory.com/123")
    cases.append((
        "numeric_post_url",
        cfg is not None and cfg.get("_slug_board") == "kevin0960",
        f"got {cfg and cfg.get('_slug_board')!r}",
    ))

    # 3) 카테고리 URL — 전체 RSS 로 조용히 바꾸면 feed 정체성이 달라지므로 미인식
    cfg = _try("https://leedakyeong.tistory.com/category/Python/Pandas%20Tutorial")
    cases.append((
        "category_url",
        cfg is None,
        f"got {cfg!r}",
    ))

    # 4) 블로그 루트 URL
    cfg = _try("https://leedakyeong.tistory.com/")
    cases.append((
        "root_url",
        cfg is not None and cfg.get("_slug_board") == "leedakyeong",
        f"got {cfg and cfg.get('_slug_board')!r}",
    ))

    # 5) tag URL — per-tag RSS 가 보장되지 않으므로 미인식
    cfg = _try("https://leedakyeong.tistory.com/tag/pandas")
    cases.append((
        "tag_url",
        cfg is None,
        f"got {cfg!r}",
    ))

    # 6) www.tistory.com/ — multi-blog hub, recognizer reject 영역. 이 인식기는 None
    cfg = _try("https://www.tistory.com/")
    cases.append(("www_root_rejected", cfg is None, f"got {cfg!r}"))

    # 7) m.tistory.com — 모바일 host. 같은 이유로 reserved
    cfg = _try("https://m.tistory.com/foo")
    cases.append(("m_subdomain_rejected", cfg is None, f"got {cfg!r}"))

    # 8) strategy=handwritten + adapter=TistoryRssAdapter
    cfg = _try("https://leedakyeong.tistory.com/")
    cases.append((
        "adapter_handwritten",
        cfg is not None and cfg.get("strategy") == "handwritten" and cfg.get("adapter") == "TistoryRssAdapter",
        f"got strategy={cfg and cfg.get('strategy')!r} adapter={cfg and cfg.get('adapter')!r}",
    ))

    # 9) custom domain (e.g. blog.example.com on Tistory backend) — host 판별 불가, None
    cfg = _try("https://blog.example.com/foo")
    cases.append(("custom_domain_unmatched", cfg is None, f"got {cfg!r}"))

    # 10) recognize() integration — recognize() 가 cfg 에 _recognized_platform=tistory 박는지
    from engine.recognizers import recognize
    cfg = recognize("https://leedakyeong.tistory.com/entry/foo")
    cases.append((
        "recognize_integration",
        cfg is not None and cfg.get("_recognized_platform") == "tistory",
        f"got platform={cfg and cfg.get('_recognized_platform')!r}",
    ))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
