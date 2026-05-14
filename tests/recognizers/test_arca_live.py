"""engine.recognizers.arca_live — URL → config 변환 (특히 ?category 처리).

이 모듈은 회귀 방지용: 2026-05-14 까지 recognizer 가 `?category=` 를 통째로 무시해서
사용자가 채널 내 특정 탭을 구독하려고 해도 채널 전체로 등록됐던 버그가 있었다.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.arca_live import _build, PATTERNS

    pat = PATTERNS[0][0]

    def _build_for(url: str):
        m = pat.search(url)
        if m is None:
            return None
        return _build(m, url)

    cases: list[tuple[str, bool, str]] = []

    # 1) 기본 — 채널만, query 없음 → category 없는 config
    cfg = _build_for("https://arca.live/b/akendfield")
    cases.append((
        "no_query",
        cfg is not None and cfg["kwargs"] == {"channel": "akendfield", "include_notices": True},
        f"got {cfg and cfg.get('kwargs')!r}",
    ))

    # 2) ?category=공식 — kwargs.category 에 반영
    cfg = _build_for("https://arca.live/b/akendfield?category=공식")
    cases.append((
        "with_category",
        cfg is not None and cfg["kwargs"].get("category") == "공식",
        f"got {cfg and cfg.get('kwargs')!r}",
    ))

    # 3) ?category=공식&p=2 — category 만 추출, p 는 무시(허용 키)
    cfg = _build_for("https://arca.live/b/akendfield?category=공식&p=2")
    cases.append((
        "category_with_page",
        cfg is not None and cfg["kwargs"].get("category") == "공식",
        f"got {cfg and cfg.get('kwargs')!r}",
    ))

    # 4) 알 수 없는 query 키 — None 반환(fast-path 거부, probe/gemini 경로로 폴백)
    cfg = _build_for("https://arca.live/b/akendfield?unknown_key=x")
    cases.append((
        "unknown_query_rejected",
        cfg is None,
        f"got {cfg!r}",
    ))

    # 5) 같은 key 가 두 번 — 어느 값을 원했는지 모호 → None
    cfg = _build_for("https://arca.live/b/akendfield?category=a&category=b")
    cases.append((
        "multi_value_category_rejected",
        cfg is None,
        f"got {cfg!r}",
    ))

    # 6) _source_url 에 category 가 url-quote 형태로 들어감 (slug 와 무관, 사람이 보는 메타용)
    cfg = _build_for("https://arca.live/b/akendfield?category=공식")
    src = cfg.get("_source_url") if cfg else ""
    cases.append((
        "source_url_keeps_category",
        cfg is not None and "category=" in src and ("공식" in src or "%EA%B3%B5%EC%8B%9D" in src),
        f"got {src!r}",
    ))

    # 7) adapter 가 ArcaLiveAdapter — strategy=handwritten
    cfg = _build_for("https://arca.live/b/akendfield?category=공식")
    cases.append((
        "adapter_handwritten",
        cfg is not None and cfg.get("strategy") == "handwritten" and cfg.get("adapter") == "ArcaLiveAdapter",
        f"got strategy={cfg and cfg.get('strategy')!r} adapter={cfg and cfg.get('adapter')!r}",
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
