"""engine.recognizers.hoyolab — HoYoLAB official 게시판 httpx_json config.

round-trip: 기존 자동생성 config 3건(circles 2/6/8)을 builder 가 *기능 필드* 동일하게 재현하는지.
(builder 가 추가하는 _note/_source_url, recognize() 가 박는 _recognized_platform 은 비교 제외.)
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

# builder 출력 vs 기존 config 비교 시 무시할 메타 키
# (_slug_board 는 recognizer 가 추가하는 slug 전용 키 — 옛 fallback config 엔 없음)
_IGNORE = {"_recognized_platform", "_source_url", "_note", "_slug_board"}


def _functional(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _IGNORE}


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.hoyolab import _build, PATTERNS
    from engine.recognizers import recognize

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    # 1) gid 추출 정확 (2=genshin)
    cfg = _try("https://www.hoyolab.com/circles/2/0/official?lang=ko-kr")
    cases.append(("gid2_board", cfg is not None and cfg.get("board") == "circles_2_official",
                  f"got {cfg and cfg.get('board')!r}"))

    # 2) list API url_template 에 gid 박힘
    cfg = _try("https://www.hoyolab.com/circles/6/0/official?lang=ko-kr")
    ok = cfg is not None and "gids=6&type=1" in cfg["list"]["url_template"]
    cases.append(("gid6_api_template", ok, f"got {cfg and cfg['list']['url_template']!r}"))

    # 3) round-trip: repo 의 기존 hoyolab config 전부 재현 (기능 필드 동일)
    repro_ok, repro_detail = True, []
    for p in sorted(glob.glob("configs/host_hoyolab-com_circles_*.json")):
        existing = json.load(open(p, encoding="utf-8"))
        url = (existing.get("headers") or {}).get("Referer")
        built = _try(url) if url else None
        if built is None:
            repro_ok = False
            repro_detail.append(f"{Path(p).name}: builder None (url={url})")
            continue
        if _functional(built) != _functional(existing):
            repro_ok = False
            # 어느 키가 다른지
            diffs = [k for k in set(_functional(built)) | set(_functional(existing))
                     if _functional(built).get(k) != _functional(existing).get(k)]
            repro_detail.append(f"{Path(p).name}: diff keys {diffs}")
    cases.append(("roundtrip_reproduces_existing", repro_ok,
                  "; ".join(repro_detail) or "all reproduced"))

    # 4) recognize() 통합 — _recognized_platform=hoyolab
    cfg = recognize("https://www.hoyolab.com/circles/8/0/official?lang=ko-kr")
    cases.append(("recognize_integration",
                  cfg is not None and cfg.get("_recognized_platform") == "hoyolab",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    # 5) lang 기본값 (query 없으면 ko-kr)
    cfg = _try("https://www.hoyolab.com/circles/2/0/official")
    cases.append(("lang_default_kokr",
                  cfg is not None and cfg["headers"]["x-rpc-language"] == "ko-kr",
                  f"got {cfg and cfg['headers'].get('x-rpc-language')!r}"))

    # 6) non-official 게시판은 매칭 안 함 (official literal 요구)
    cfg = _try("https://www.hoyolab.com/circles/2/0/recommend?lang=ko-kr")
    cases.append(("non_official_unmatched", cfg is None, f"got {cfg!r}"))

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
