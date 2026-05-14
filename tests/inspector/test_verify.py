"""bot.inspector.verify_recognize — URL → recognize + fetch_list 시뮬.

fetch_list 는 네트워크 + playwright 가 필요하므로 *그 부분은 검증 못 함*.
이 테스트는 recognize() 결과 + 출력 포맷만 검증한다 — 진짜 fetch 가 깨져도 posts=[] / error 채워져
반환 구조만 안전하면 통과.
"""
from __future__ import annotations

import asyncio


def run() -> list[tuple[str, bool, str]]:
    from bot import inspector
    cases: list[tuple[str, bool, str]] = []

    # 1) arca-tab URL → recognize() 가 cfg 반환 + kwargs.category 채워짐
    res = asyncio.run(inspector.verify_recognize(
        "https://arca.live/b/akendfield?category=공식", n=0))
    cfg = res.get("recognized") or {}
    kw = cfg.get("kwargs") or {}
    cases.append((
        "arca_tab_recognized",
        cfg.get("_recognized_platform") == "arca-live" and kw.get("category") == "공식",
        f"got plat={cfg.get('_recognized_platform')!r} kwargs={kw!r}",
    ))

    # 2) 알 수 없는 query 키 — recognize() None (fast-path 거부)
    res = asyncio.run(inspector.verify_recognize(
        "https://arca.live/b/akendfield?weird_param=1", n=0))
    cases.append((
        "unknown_query_rejected",
        res.get("recognized") is None,
        f"got {res.get('recognized')!r}",
    ))

    # 3) 결과 dict 구조 — 키 모두 존재
    res = asyncio.run(inspector.verify_recognize(
        "https://arca.live/b/akendfield", n=0))
    required = {"url", "slug", "recognized", "posts", "error"}
    cases.append((
        "result_keys_complete",
        set(res) >= required and isinstance(res["posts"], list),
        f"keys={set(res)}",
    ))

    # 4) format_verify_result — None 케이스도 안 터지는지
    res_none = {"url": "https://example.com/x", "slug": "example.com_x",
                "recognized": None, "posts": [], "error": None}
    text = inspector.format_verify_result(res_none)
    cases.append((
        "format_none_safe",
        "매칭 안 됨" in text and "example.com_x" in text,
        f"len={len(text)}",
    ))

    # 5) format_verify_result — posts 있는 케이스 + 카테고리 분포 라인
    res_ok = {
        "url": "https://arca.live/b/x?category=공식",
        "slug": "arca.live_b_x_category_공식",
        "recognized": {"_recognized_platform": "arca-live", "strategy": "handwritten",
                        "adapter": "ArcaLiveAdapter", "site": "arca.live", "board": "x",
                        "kwargs": {"channel": "x", "category": "공식"}},
        "posts": [
            {"post_id": "1", "title": "a", "url": "u1", "category": "공식", "published_at": None},
            {"post_id": "2", "title": "b", "url": "u2", "category": "공식", "published_at": None},
            {"post_id": "3", "title": "c", "url": "u3", "category": "정보", "published_at": None},
        ],
        "error": None,
    }
    text = inspector.format_verify_result(res_ok)
    cases.append((
        "format_with_posts",
        "카테고리 분포" in text and "`공식`=2" in text and "`정보`=1" in text,
        f"snippet={text[-200:]!r}",
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
