"""engine.recognizers.github_releases — GitHub Releases httpx_html config.

round-trip 모델 주의: 기존 자동생성 config 와 byte-match 안 함 (recognizer 모듈 docstring 참고 —
LLM 이 repo 마다 다른/버그난 selector·board 를 뽑았다). 대신:
  - 멤버 URL → board=owner/repo·url_template 결정적 추출
  - /releases 가 아닌 같은-host config (tree/main, repo 홈) → builder None (cluster 제외 확인)
  - 같은-host 다른-종류 페이지 negative (false-match 핵심 가드)
"""
from __future__ import annotations

import glob
import json
from pathlib import Path
from urllib.parse import urlsplit


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.github_releases import _build, PATTERNS
    from engine.recognizers import recognize, recognize_reject

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    # 1) board=owner/repo + url_template 정확 추출
    cfg = _try("https://github.com/anthropics/claude-code/releases")
    cases.append((
        "board_extract",
        cfg is not None and cfg.get("board") == "anthropics/claude-code"
        and cfg["list"]["url_template"] == "https://github.com/{board}/releases",
        f"got board={cfg and cfg.get('board')!r}",
    ))

    # 2) _slug_board owner_repo
    cfg = _try("https://github.com/oven-sh/bun/releases")
    cases.append((
        "slug_board",
        cfg is not None and cfg.get("_slug_board") == "oven-sh_bun",
        f"got {cfg and cfg.get('_slug_board')!r}",
    ))

    # 3) round-trip over fetched member configs:
    #    Referer 가 /releases 폼이면 builder 가 board=owner/repo 정확 추출.
    #    /releases 아닌 멤버(tree/main, repo 홈)는 builder None (cluster 에서 제외돼야).
    matched_n, excluded_n = 0, 0
    detail: list[str] = []
    ok = True
    for p in sorted(glob.glob("configs/host_github-com_*.json")):
        existing = json.load(open(p, encoding="utf-8"))
        url = (existing.get("headers") or {}).get("Referer")
        built = _try(url) if url else None
        path_parts = urlsplit(url).path.strip("/").split("/") if url else []
        is_release = url is not None and url.rstrip("/").endswith("/releases")
        if is_release:
            matched_n += 1
            expect_board = f"{path_parts[0]}/{path_parts[1]}"
            if built is None:
                ok = False
                detail.append(f"{Path(p).name}: release URL 인데 builder None ({url})")
            elif built.get("board") != expect_board:
                ok = False
                detail.append(f"{Path(p).name}: board {built.get('board')!r} != {expect_board!r}")
        else:
            excluded_n += 1
            if built is not None:
                ok = False
                detail.append(f"{Path(p).name}: non-release URL({url}) 인데 builder 매칭 — 제외 실패")
    # anti-vacuous: release 멤버 ≥15 비교 강제
    if matched_n < 15:
        ok = False
        detail.append(f"release 멤버 {matched_n}개(<15) — configs/host_github-com_*.json 확인 (vacuous-pass 방지)")
    cases.append((
        "roundtrip_members",
        ok,
        f"release {matched_n} / 제외 {excluded_n} · " + ("; ".join(detail) or "all ok"),
    ))

    # 4) recognize() 통합
    cfg = recognize("https://github.com/rust-lang/rust/releases")
    cases.append((
        "recognize_integration",
        cfg is not None and cfg.get("_recognized_platform") == "github-releases",
        f"got {cfg and cfg.get('_recognized_platform')!r}",
    ))

    # 5) 다른-host negative
    cases.append((
        "other_host_neg",
        recognize("https://gitlab.com/foo/bar/releases") is None,
        "gitlab 매칭되면 안 됨",
    ))

    # 6) 같은-host 다른-종류 negative (false-match 핵심 가드 — SKILL §4):
    #    /releases literal 이 유일한 방어. repo 홈·issues·pulls·tree·wiki·개별 release 는 잡으면 안 됨.
    same_host_neg = [
        "https://github.com/anthropics/claude-code",              # repo 홈
        "https://github.com/anthropics/claude-code/issues",        # issues
        "https://github.com/anthropics/claude-code/pulls",         # PR
        "https://github.com/anthropics/claude-code/wiki",          # wiki
        "https://github.com/anthropics/claude-code/tree/main",     # 소스 트리
        "https://github.com/anthropics/claude-code/commits",       # commits
        "https://github.com/anthropics/claude-code/releases/tag/v1.0.0",  # 개별 release(article)
        "https://github.com/anthropics",                           # owner 프로필
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "github-releases"
        tag = u.split("github.com")[1][:30]
        cases.append((
            f"same_host_neg[{tag}]",
            not hit,
            f"recognize→ {r and r.get('_recognized_platform')!r} (None 이어야)",
        ))

    # 7) reject 충돌 없음 — release URL 이 article_page_reject 에 안 걸려야 (recognizer 무력화 방지)
    cases.append((
        "no_reject_conflict",
        recognize_reject("https://github.com/anthropics/claude-code/releases") is None,
        f"got {recognize_reject('https://github.com/anthropics/claude-code/releases')!r}",
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
