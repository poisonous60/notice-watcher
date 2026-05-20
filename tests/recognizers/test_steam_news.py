"""engine.recognizers.steam_news — Steam 앱 뉴스 피드 httpx_html config.

round-trip 모델 주의: 기존 자동생성 config 와 byte-match 안 함 (recognizer 모듈 docstring 참고 —
LLM 이 멤버마다 다른/버그난 헤더·selector·board 를 뽑았다). 대신:
  - 멤버 URL → board=appid·url_template 결정적 추출
  - /feeds/news/app/<appid>/ 아닌 같은-host config (daily_deals.xml, news.xml) → builder None (cluster 제외 확인)
  - 같은-host 다른-종류 페이지 negative (false-match 핵심 가드)
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.steam_news import _build, PATTERNS
    from engine.recognizers import recognize, recognize_reject

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    # 1) board=appid + url_template 정확 추출
    cfg = _try("https://store.steampowered.com/feeds/news/app/730/")
    cases.append((
        "board_extract",
        cfg is not None and cfg.get("board") == "730"
        and cfg["list"]["url_template"] == "https://store.steampowered.com/feeds/news/app/{board}/",
        f"got board={cfg and cfg.get('board')!r}",
    ))

    # 2) _slug_board=appid
    cfg = _try("https://store.steampowered.com/feeds/news/app/570/")
    cases.append((
        "slug_board",
        cfg is not None and cfg.get("_slug_board") == "570",
        f"got {cfg and cfg.get('_slug_board')!r}",
    ))

    # 3) round-trip over fetched member configs:
    #    멤버의 피드 URL = list.url_template 에 board 치환. /feeds/news/app/<appid>/ 폼이면
    #    builder 가 board=appid 정확 추출. daily_deals.xml·news.xml 멤버는 builder None (제외돼야).
    app_re = re.compile(r"/feeds/news/app/(\d+)/?$")
    matched_n, excluded_n = 0, 0
    detail: list[str] = []
    ok = True
    for p in sorted(glob.glob("configs/host_store-steampowe_feeds_*.json")):
        existing = json.load(open(p, encoding="utf-8"))
        tmpl = ((existing.get("list") or {}).get("url_template")) or ""
        board = existing.get("board") or ""
        feed_url = tmpl.replace("{board}", board)
        built = _try(feed_url) if feed_url else None
        m = app_re.search(feed_url)
        if m:
            matched_n += 1
            expect_board = m.group(1)
            if built is None:
                ok = False
                detail.append(f"{Path(p).name}: app-feed URL 인데 builder None ({feed_url})")
            elif built.get("board") != expect_board:
                ok = False
                detail.append(f"{Path(p).name}: board {built.get('board')!r} != {expect_board!r}")
        else:
            excluded_n += 1
            if built is not None:
                ok = False
                detail.append(f"{Path(p).name}: non-app-feed URL({feed_url}) 인데 builder 매칭 — 제외 실패")
    # anti-vacuous: app-feed 멤버 ≥10 비교 강제
    if matched_n < 10:
        ok = False
        detail.append(f"app-feed 멤버 {matched_n}개(<10) — configs/host_store-steampowe_feeds_*.json 확인 (vacuous-pass 방지)")
    cases.append((
        "roundtrip_members",
        ok,
        f"app-feed {matched_n} / 제외 {excluded_n} · " + ("; ".join(detail) or "all ok"),
    ))

    # 4) recognize() 통합 (피드 URL)
    cfg = recognize("https://store.steampowered.com/feeds/news/app/440/")
    cases.append((
        "recognize_integration",
        cfg is not None and cfg.get("_recognized_platform") == "steam-news",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))

    # 4b) 허브 URL(사람-paste) → 같은 피드 config 로 정규화 (board=appid, list=피드)
    cfg = recognize("https://store.steampowered.com/news/app/105600/")
    cases.append((
        "hub_url_normalizes_to_feed",
        cfg is not None and cfg.get("_recognized_platform") == "steam-news"
        and cfg.get("board") == "105600"
        and cfg["list"]["url_template"] == "https://store.steampowered.com/feeds/news/app/{board}/",
        f"got board={cfg and cfg.get('board')!r} tmpl={cfg and cfg['list']['url_template']!r}",
    ))

    # 5) 다른-host negative
    cases.append((
        "other_host_neg",
        recognize("https://steamcommunity.com/feeds/news/app/440/") is None,
        "steamcommunity 매칭되면 안 됨",
    ))

    # 6) 같은-host 다른-종류 negative (false-match 핵심 가드 — SKILL §4):
    #    feed/hub literal + end-anchor 가 유일한 방어. (허브 /news/app/<id>/ 는 의도적 positive — 4b 참고)
    same_host_neg = [
        "https://store.steampowered.com/feeds/daily_deals.xml",        # appid 없는 전역 피드
        "https://store.steampowered.com/feeds/news.xml",               # 전역 뉴스 피드
        "https://store.steampowered.com/news/app/730/view/123",        # 단일 article
        "https://store.steampowered.com/feeds/news/app/730/view/456",  # 피드 하위 article
        "https://store.steampowered.com/app/730/",                     # 스토어 페이지(뉴스 아님)
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "steam-news"
        tag = u.split("steampowered.com")[1][:30]
        cases.append((
            f"same_host_neg[{tag}]",
            not hit,
            f"recognize→ {r and r.get('_recognized_platform')!r} (None 이어야)",
        ))

    # 7) reject 충돌 없음 — 피드 URL 이 article_page_reject 에 안 걸려야 (recognizer 무력화 방지)
    cases.append((
        "no_reject_conflict",
        recognize_reject("https://store.steampowered.com/feeds/news/app/730/") is None,
        f"got {recognize_reject('https://store.steampowered.com/feeds/news/app/730/')!r}",
    ))

    return cases


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
